from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import resolve_config
from ..data_sync import sync_data_directory, sync_data_directory_session
from ..dependencies import get_db_session
from ..db import connect_database, get_engine, get_session_factory, is_sqlite_database_url
from ..git_store import GitStoreError, pull_latest_changes
from ..schemas import StartupResolveRequest
from ..yaml_store import write_all_to_data_dir, write_all_to_data_dir_session


def create_ops_router(reconciliation: dict[str, Any]) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health(db: Session = Depends(get_db_session)) -> dict[str, str]:
        db.execute(text("SELECT 1;"))
        config = resolve_config()
        return {
            "status": "ok",
            "database": "ok",
            "output_dir": str(config.output_dir),
        }

    @router.get("/startup/status")
    def startup_status() -> dict[str, Any]:
        return {
            "reconciliation_needed": reconciliation["needed"],
            "report": reconciliation["report"],
        }

    @router.post("/startup/resolve")
    def startup_resolve(request: StartupResolveRequest) -> dict[str, bool]:
        config = resolve_config()
        if not is_sqlite_database_url(config.database_url):
            if request.direction == "yaml_to_db":
                engine = get_engine(config)
                session_factory = get_session_factory(engine)
                with session_factory() as db:
                    sync_data_directory_session(db, config.data_dir)
                    db.commit()
            elif request.direction == "db_to_yaml":
                engine = get_engine(config)
                session_factory = get_session_factory(engine)
                with session_factory() as db:
                    write_all_to_data_dir_session(db, config.data_dir)
        else:
            with connect_database(config) as connection:
                if request.direction == "yaml_to_db":
                    sync_data_directory(connection, config.data_dir)
                    connection.commit()
                elif request.direction == "db_to_yaml":
                    write_all_to_data_dir(connection, config.data_dir)
                    connection.commit()
        reconciliation["needed"] = False
        reconciliation["report"] = None
        return {"ok": True}

    @router.post("/data/pull")
    def pull_yaml_data() -> dict[str, Any]:
        config = resolve_config()
        if config.git_repo_path is None or not config.git_user_name or not config.git_user_email:
            raise HTTPException(status_code=400, detail="Git configuration incomplete (GIT_REPO_PATH, GIT_USER_NAME, GIT_USER_EMAIL)")

        try:
            changed = pull_latest_changes(
                config.git_repo_path,
                user_name=config.git_user_name,
                user_email=config.git_user_email,
            )

            synced = None
            if changed:
                if is_sqlite_database_url(config.database_url):
                    with connect_database(config) as connection:
                        synced = sync_data_directory(connection, config.data_dir)
                        connection.commit()
                else:
                    engine = get_engine(config)
                    session_factory = get_session_factory(engine)
                    with session_factory() as db:
                        synced = sync_data_directory_session(db, config.data_dir)
                        db.commit()

            return {
                "changed": changed,
                "synced": {
                    "businesses": synced.businesses_synced,
                    "campaigns": synced.campaigns_synced,
                } if synced else None,
                "repo": str(config.git_repo_path),
            }
        except GitStoreError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/data/sync")
    def sync_yaml_data() -> dict[str, Any]:
        config = resolve_config()
        if is_sqlite_database_url(config.database_url):
            with connect_database(config) as connection:
                summary = sync_data_directory(connection, config.data_dir)
                connection.commit()
        else:
            engine = get_engine(config)
            session_factory = get_session_factory(engine)
            with session_factory() as db:
                summary = sync_data_directory_session(db, config.data_dir)
                db.commit()
        return {
            "businesses_synced": summary.businesses_synced,
            "campaigns_synced": summary.campaigns_synced,
            "data_dir": str(config.data_dir),
        }

    return router
