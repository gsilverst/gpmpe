from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.orm import Session

from .chat import (
    ChatSessionStore,
    ParsedCloneCommand,
    ParsedQueryCommand,
    apply_chat_command_session,
    parse_chat_command,
    parse_clone_command,
    parse_query_command,
    parse_session_context_command,
)
from .config import resolve_config
from .data_sync import (
    clone_campaign_directory_session,
    compare_db_to_yaml,
    compare_db_to_yaml_session,
    discover_data_directory,
    sync_data_directory,
    sync_data_directory_session,
)
from .dependencies import (
    get_db_session,
    require_business as _require_business,
    require_campaign as _require_campaign,
)
from .db import (
    connect_database,
    get_engine,
    get_session_factory,
    initialize_database,
    is_sqlite_database_url,
)
from .git_store import GitStoreError, pull_latest_changes
from .llm import translate_and_apply_session
from .middleware import RequestIDMiddleware
from .models import (
    Business,
    Campaign,
    CampaignComponent,
    CampaignComponentItem,
)
from .routes.artifacts import router as artifacts_router
from .routes.business_campaigns import router as business_campaigns_router
from .routes.components import router as components_router
from .routes.data_manager import router as data_manager_router
from .routes.offers_assets import router as offers_assets_router
from .routes.templates import router as templates_router
from .schemas import (
    ChatMessageRequest,
    StartupResolveRequest,
)
from .services.yaml_persistence import persist_campaign_yaml_session_or_raise
from .yaml_store import (
    delete_yaml_state_for_campaign,
    write_all_to_data_dir,
    write_all_to_data_dir_session,
)


# Module-level reconciliation state (single-process; reset on each lifespan startup).
_reconciliation: dict[str, Any] = {"needed": False, "report": None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _reconciliation
    _reconciliation = {"needed": False, "report": None}

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
                _reconciliation = {
                    "needed": True,
                    "report": {
                        "yaml_only": report.yaml_only,
                        "db_only": report.db_only,
                        "content_differs": report.content_differs,
                        "db_latest_updated_at": report.db_latest_updated_at,
                        "yaml_latest_mtime": report.yaml_latest_mtime,
                    },
                }
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
                    _reconciliation = {
                        "needed": True,
                        "report": {
                            "yaml_only": report.yaml_only,
                            "db_only": report.db_only,
                            "content_differs": report.content_differs,
                            "db_latest_updated_at": report.db_latest_updated_at,
                            "yaml_latest_mtime": report.yaml_latest_mtime,
                        },
                    }

    yield

    _reconciliation = {"needed": False, "report": None}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
_logger = logging.getLogger("gpmpe")


def _resolve_component_session(db: Session, campaign_id: int, component_ref: str) -> CampaignComponent | None:
    normalized = component_ref.lower()
    return (
        db.query(CampaignComponent)
        .filter(
            CampaignComponent.campaign_id == campaign_id,
            (
                func.lower(CampaignComponent.component_key) == normalized
            ) | (
                func.lower(CampaignComponent.display_title) == normalized
            ),
        )
        .order_by(CampaignComponent.id.asc())
        .first()
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

    @app.get("/health")
    def health(db: Session = Depends(get_db_session)) -> dict[str, str]:
        from sqlalchemy import text
        db.execute(text("SELECT 1;"))
        config = resolve_config()
        return {
            "status": "ok",
            "database": "ok",
            "output_dir": str(config.output_dir),
        }

    @app.get("/startup/status")
    def startup_status() -> dict[str, Any]:
        return {
            "reconciliation_needed": _reconciliation["needed"],
            "report": _reconciliation["report"],
        }

    @app.post("/startup/resolve")
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
            # "skip" -> no data changes
        else:
            from .db import connect_database
            with connect_database(config) as connection:
                if request.direction == "yaml_to_db":
                    sync_data_directory(connection, config.data_dir)
                    connection.commit()
                elif request.direction == "db_to_yaml":
                    write_all_to_data_dir(connection, config.data_dir)
                    connection.commit()
                # "skip" -> no data changes
        _reconciliation["needed"] = False
        _reconciliation["report"] = None
        return {"ok": True}

    @app.post("/chat/sessions", status_code=201)
    def create_chat_session() -> dict[str, str]:
        return {"session_id": chat_store.create()}

    @app.get("/chat/sessions/{session_id}")
    def get_chat_session_history(session_id: str) -> dict[str, Any]:
        if not chat_store.exists(session_id):
            raise HTTPException(status_code=404, detail="Chat session not found")
        return {"session_id": session_id, "history": chat_store.history(session_id)}

    @app.post("/chat/sessions/{session_id}/messages")
    def post_chat_message(
        session_id: str,
        payload: ChatMessageRequest,
        db: Session = Depends(get_db_session),
    ) -> dict[str, Any]:
        if not chat_store.exists(session_id):
            raise HTTPException(status_code=404, detail="Chat session not found")

        config = resolve_config()

        def _sync_active_campaign_context(active_campaign_id: int | None) -> None:
            previous_campaign_id = chat_store.get_context(session_id).get("active_campaign_id")
            if previous_campaign_id != active_campaign_id:
                chat_store.set_context_value(session_id, "active_component_ref", None)
            chat_store.set_context_value(session_id, "active_campaign_id", active_campaign_id)

        clone_cmd = parse_clone_command(payload.message)
        if clone_cmd is not None:
            try:
                record = clone_campaign_directory_session(
                    db,
                    config.data_dir,
                    source_campaign_name=clone_cmd.source_campaign_name,
                    new_campaign_name=clone_cmd.new_campaign_name,
                    business_name=clone_cmd.business_name,
                )
                db.commit()
            except ValueError as exc:
                db.rollback()
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            new_campaign = (
                db.query(Campaign)
                .filter(Campaign.campaign_name == clone_cmd.new_campaign_name)
                .order_by(Campaign.id.desc())
                .first()
            )
            new_campaign_id = new_campaign.id if new_campaign else None
            new_business_id = new_campaign.business_id if new_campaign else None
            _sync_active_campaign_context(new_campaign_id)
            chat_store.append(session_id, "user", payload.message)
            chat_store.append(
                session_id,
                "system",
                f"Cloned campaign '{clone_cmd.source_campaign_name}' to '{clone_cmd.new_campaign_name}'",
            )
            return {
                "session_id": session_id,
                "result": {
                    "target": "clone",
                    "source_campaign_name": clone_cmd.source_campaign_name,
                    "new_campaign_name": clone_cmd.new_campaign_name,
                    "new_campaign_title": record.payload.get("title"),
                    "new_campaign_id": new_campaign_id,
                    "new_business_id": new_business_id,
                },
                "history": chat_store.history(session_id),
            }

        if payload.campaign_id is None:
            raise HTTPException(status_code=400, detail="campaign_id is required for edit commands")

        _sync_active_campaign_context(payload.campaign_id)
        campaign = _require_campaign(db, payload.campaign_id)
        business_display_name = campaign.business.display_name

        context_cmd = parse_session_context_command(payload.message)
        if context_cmd is not None:
            component = _resolve_component_session(db, payload.campaign_id, context_cmd.component_ref)
            if component is None:
                raise HTTPException(status_code=404, detail="Component not found")
            chat_store.set_context_value(session_id, "active_component_ref", component.component_key)
            chat_store.append(session_id, "user", payload.message)
            chat_store.append(
                session_id,
                "system",
                f"Set active component context to '{component.component_key}'",
            )
            return {
                "session_id": session_id,
                "result": {
                    "target": "context",
                    "context_type": "component",
                    "component": {
                        "id": component.id,
                        "campaign_id": component.campaign_id,
                        "component_key": component.component_key,
                        "component_kind": component.component_kind,
                        "display_title": component.display_title,
                    },
                    "message": f"Working on component {component.component_key}",
                },
                "history": chat_store.history(session_id),
            }

        query_cmd = parse_query_command(payload.message)
        if query_cmd is not None:
            session_context = chat_store.get_context(session_id)
            if query_cmd.query_type == "list_components":
                components = (
                    db.query(CampaignComponent)
                    .filter(CampaignComponent.campaign_id == payload.campaign_id)
                    .order_by(CampaignComponent.display_order.asc(), CampaignComponent.id.asc())
                    .all()
                )
                components_list = [
                    {
                        "component_key": row.component_key,
                        "display_title": row.display_title,
                        "component_kind": row.component_kind,
                        "display_order": row.display_order,
                    }
                    for row in components
                ]
                if components_list:
                    lines = [
                        f"{i + 1}. {c['component_key']} — {c['display_title'] or '(no title)'}"
                        for i, c in enumerate(components_list)
                    ]
                    message = "Components of the current promotion:\n" + "\n".join(lines)
                else:
                    message = "This promotion has no components yet."
                result: dict[str, Any] = {
                    "target": "query",
                    "query_type": "list_components",
                    "components": components_list,
                    "message": message,
                }
            else:  # list_items
                active_component_ref = session_context.get("active_component_ref")
                if not active_component_ref:
                    result = {
                        "target": "clarify",
                        "message": (
                            "No active component is set. "
                            "Reference a component first, for example: "
                            "'change the name of the weekday-specials component to …' "
                            "or 'I am working on the weekday-specials component'."
                        ),
                    }
                else:
                    component = (
                        db.query(CampaignComponent)
                        .filter(
                            CampaignComponent.campaign_id == payload.campaign_id,
                            CampaignComponent.component_key == active_component_ref,
                        )
                        .first()
                    )
                    if component is None:
                        result = {
                            "target": "clarify",
                            "message": f"Component '{active_component_ref}' not found in this campaign.",
                        }
                    else:
                        items = sorted(component.items, key=lambda row: (row.display_order, row.id))
                        items_list = [
                            {
                                "item_name": row.item_name,
                                "item_kind": row.item_kind,
                                "item_value": row.item_value,
                                "duration_label": row.duration_label,
                                "display_order": row.display_order,
                            }
                            for row in items
                        ]
                        if items_list:
                            lines = [
                                f"{i + 1}. {it['item_name']}"
                                + (f" — {it['item_value']}" if it["item_value"] else "")
                                + (f" ({it['duration_label']})" if it["duration_label"] else "")
                                for i, it in enumerate(items_list)
                            ]
                            message = f"Items in '{active_component_ref}':\n" + "\n".join(lines)
                        else:
                            message = f"Component '{active_component_ref}' has no items yet."
                        result = {
                            "target": "query",
                            "query_type": "list_items",
                            "component_key": active_component_ref,
                            "items": items_list,
                            "message": message,
                        }
            chat_store.append(session_id, "user", payload.message)
            chat_store.append(session_id, "assistant", result.get("message", ""))
            return {
                "session_id": session_id,
                "result": result,
                "history": chat_store.history(session_id),
            }

        llm_warning: str | None = None
        session_context = chat_store.get_context(session_id)

        if config.openrouter_api_key:
            # LLM path: translate natural language → structured command
            try:
                result = translate_and_apply_session(
                    db,
                    payload.campaign_id,
                    config.openrouter_api_key,
                    payload.message,
                )
                if result.get("target") != "clarify":
                    if (
                        result.get("target") == "campaign"
                        and result.get("field") == "delete"
                        and result.get("deleted")
                    ):
                        delete_yaml_state_for_campaign(
                            config.data_dir,
                            business_display_name,
                            result.get("campaign_name"),
                        )
                    else:
                        persist_campaign_yaml_session_or_raise(db, config, payload.campaign_id)
                db.commit()
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                _logger.warning("LLM call failed (%s); falling back to regex router", exc)
                llm_warning = "AI assistant unavailable; falling back to command syntax."
                command = parse_chat_command(payload.message)
                result = apply_chat_command_session(
                    db,
                    payload.campaign_id,
                    command,
                    session_context=session_context,
                )
                if result.get("target") != "clarify":
                    if (
                        result.get("target") == "campaign"
                        and result.get("field") == "delete"
                        and result.get("deleted")
                    ):
                        delete_yaml_state_for_campaign(
                            config.data_dir,
                            business_display_name,
                            result.get("campaign_name"),
                        )
                    else:
                        persist_campaign_yaml_session_or_raise(db, config, payload.campaign_id)
                db.commit()
        else:
            # Regex-only path (no API key configured)
            command = parse_chat_command(payload.message)
            result = apply_chat_command_session(
                db,
                payload.campaign_id,
                command,
                session_context=session_context,
            )
            if result.get("target") != "clarify":
                if (
                    result.get("target") == "campaign"
                    and result.get("field") == "delete"
                    and result.get("deleted")
                ):
                    delete_yaml_state_for_campaign(
                        config.data_dir,
                        business_display_name,
                        result.get("campaign_name"),
                    )
                else:
                    persist_campaign_yaml_session_or_raise(db, config, payload.campaign_id)
            db.commit()

        chat_store.append(session_id, "user", payload.message)
        if result.get("target") == "clarify":
            chat_store.append(session_id, "assistant", result.get("message", ""))
        else:
            if result.get("target") == "component":
                if result.get("field") == "delete":
                    chat_store.set_context_value(session_id, "active_component_ref", None)
                else:
                    chat_store.set_context_value(
                        session_id,
                        "active_component_ref",
                        result.get("component", {}).get("component_key"),
                    )
            elif result.get("target") == "component_item":
                component_key = result.get("component", {}).get("component_key")
                if component_key is not None:
                    chat_store.set_context_value(session_id, "active_component_ref", component_key)
            summary_field = result.get("field", result.get("target", "unknown"))
            chat_store.append(
                session_id,
                "system",
                f"Applied {result['target']} update for field '{summary_field}'",
            )

        response: dict[str, Any] = {
            "session_id": session_id,
            "result": result,
            "history": chat_store.history(session_id),
        }
        if llm_warning:
            response["warning"] = llm_warning
        return response

    @app.post("/data/pull")
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

            # If changes were pulled, we should probably trigger a sync to DB automatically
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
                    "campaigns": synced.campaigns_synced
                } if synced else None,
                "repo": str(config.git_repo_path)
            }
        except GitStoreError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/data/sync")
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

    app.include_router(artifacts_router)
    app.include_router(business_campaigns_router)
    app.include_router(components_router)
    app.include_router(data_manager_router)
    app.include_router(offers_assets_router)
    app.include_router(templates_router)

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend-static")

    return app


app = create_app()
