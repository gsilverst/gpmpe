from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .chat import ChatSessionStore
from .config import resolve_config
from .data_sync import (
    compare_db_to_yaml,
    compare_db_to_yaml_session,
    discover_data_directory,
    sync_data_directory,
    sync_data_directory_session,
)
from .db import (
    connect_database,
    get_engine,
    get_session_factory,
    initialize_database,
    is_sqlite_database_url,
)
from .middleware import RequestIDMiddleware
from .models import (
    Business,
)
from .routes.admin_settings import router as admin_settings_router
from .routes.artifacts import router as artifacts_router
from .routes.business_campaigns import router as business_campaigns_router
from .routes.chat import create_chat_router
from .routes.components import router as components_router
from .routes.data_manager import router as data_manager_router
from .routes.offers_assets import router as offers_assets_router
from .routes.ops import create_ops_router
from .routes.templates import router as templates_router
from .yaml_store import (
    write_all_to_data_dir,
    write_all_to_data_dir_session,
)


# Module-level reconciliation state (single-process; reset on each lifespan startup).
_reconciliation: dict[str, Any] = {"needed": False, "report": None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _reconciliation
    _reconciliation.clear()
    _reconciliation.update({"needed": False, "report": None})

    config = resolve_config()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    initialize_database(config)

    yaml_records = discover_data_directory(config.data_dir)
    if not is_sqlite_database_url(config.database_url):
        engine = get_engine(config)
        session_factory = get_session_factory(engine)
        with session_factory() as db:
            db_count = db.query(Business).count()

        if not yaml_records and db_count > 0:
            with session_factory() as db:
                write_all_to_data_dir_session(db, config.data_dir)
        elif yaml_records and db_count == 0:
            with session_factory() as db:
                sync_data_directory_session(db, config.data_dir)
                db.commit()
        elif yaml_records:
            with session_factory() as db:
                report = compare_db_to_yaml_session(db, config.data_dir)
            if not report.in_sync:
                _reconciliation.clear()
                _reconciliation.update({
                    "needed": True,
                    "report": {
                        "yaml_only": report.yaml_only,
                        "db_only": report.db_only,
                        "content_differs": report.content_differs,
                        "db_latest_updated_at": report.db_latest_updated_at,
                        "yaml_latest_mtime": report.yaml_latest_mtime,
                    },
                })
    else:
        with connect_database(config) as connection:
            db_count = int(
                connection.execute("SELECT COUNT(*) FROM businesses;").fetchone()[0]
            )

            if not yaml_records and db_count == 0:
                # Fresh install — nothing to reconcile.
                pass
            elif not yaml_records and db_count > 0:
                # DB has data but DATA_DIR is empty → write DB state to DATA_DIR.
                write_all_to_data_dir(connection, config.data_dir)
                connection.commit()
            elif yaml_records and db_count == 0:
                # DATA_DIR has data but DB is empty → sync YAML → DB silently.
                sync_data_directory(connection, config.data_dir)
                connection.commit()
            else:
                # Both sides have data → compare and flag for reconciliation if different.
                report = compare_db_to_yaml(connection, config.data_dir)
                if not report.in_sync:
                    _reconciliation.clear()
                    _reconciliation.update({
                        "needed": True,
                        "report": {
                            "yaml_only": report.yaml_only,
                            "db_only": report.db_only,
                            "content_differs": report.content_differs,
                            "db_latest_updated_at": report.db_latest_updated_at,
                            "yaml_latest_mtime": report.yaml_latest_mtime,
                        },
                    })

    yield

    _reconciliation.clear()
    _reconciliation.update({"needed": False, "report": None})


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
def create_app() -> FastAPI:
    app = FastAPI(title="GPMPE API", version="0.1.0", lifespan=lifespan)
    chat_store = ChatSessionStore()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:3100",
            "http://localhost:3100",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)

    app.include_router(admin_settings_router)
    app.include_router(artifacts_router)
    app.include_router(business_campaigns_router)
    app.include_router(create_chat_router(chat_store))
    app.include_router(components_router)
    app.include_router(data_manager_router)
    app.include_router(offers_assets_router)
    app.include_router(create_ops_router(_reconciliation))
    app.include_router(templates_router)

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend-static")

    return app


app = create_app()
