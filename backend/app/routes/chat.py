from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..chat import (
    ChatSessionStore,
    apply_chat_command_session,
    parse_chat_command,
    parse_clone_command,
    parse_query_command,
    parse_session_context_command,
)
from ..config import resolve_config
from ..data_sync import clone_campaign_directory_session
from ..dependencies import get_db_session, require_campaign
from ..llm import translate_and_apply_session
from ..models import Campaign, CampaignComponent
from ..schemas import ChatMessageRequest
from ..services.yaml_persistence import persist_campaign_yaml_session_or_raise
from ..yaml_store import delete_yaml_state_for_campaign

_logger = logging.getLogger("gpmpe")


def _resolve_component_session(
    db: Session,
    campaign_id: int,
    component_ref: str,
) -> CampaignComponent | None:
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


def create_chat_router(chat_store: ChatSessionStore) -> APIRouter:
    router = APIRouter(prefix="/chat")

    @router.post("/sessions", status_code=201)
    def create_chat_session() -> dict[str, str]:
        return {"session_id": chat_store.create()}

    @router.get("/sessions/{session_id}")
    def get_chat_session_history(session_id: str) -> dict[str, Any]:
        if not chat_store.exists(session_id):
            raise HTTPException(status_code=404, detail="Chat session not found")
        return {"session_id": session_id, "history": chat_store.history(session_id)}

    @router.post("/sessions/{session_id}/messages")
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
        campaign = require_campaign(db, payload.campaign_id)
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
                        f"{i + 1}. {c['component_key']} - {c['display_title'] or '(no title)'}"
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
            else:
                active_component_ref = session_context.get("active_component_ref")
                if not active_component_ref:
                    result = {
                        "target": "clarify",
                        "message": (
                            "No active component is set. "
                            "Reference a component first, for example: "
                            "'change the name of the weekday-specials component to ...' "
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
                                + (f" - {it['item_value']}" if it["item_value"] else "")
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
            except Exception as exc:
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

    return router
