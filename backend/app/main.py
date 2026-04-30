from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
import json
import logging
from pathlib import Path
import sqlite3
from typing import Literal
from typing import Any
from urllib.parse import urlparse
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.middleware.base import BaseHTTPMiddleware

from .chat import (
    ChatSessionStore,
    ParsedCloneCommand,
    ParsedQueryCommand,
    apply_chat_command,
    parse_chat_command,
    parse_clone_command,
    parse_query_command,
    parse_session_context_command,
    resolve_component,
)
from .config import resolve_config
from .data_sync import clone_campaign_directory, compare_db_to_yaml, discover_data_directory, sync_data_directory
from .db import connect_database, initialize_database
from .git_store import GitStoreError, auto_commit_paths
from .llm import translate_and_apply
from .renderer import render_campaign_artifact
from .yaml_store import (
    campaign_yaml_paths_for_id,
    delete_yaml_state_for_campaign,
    persist_yaml_state_for_campaign,
    write_all_to_data_dir,
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

    with connect_database(config) as connection:
        yaml_records = discover_data_directory(config.data_dir)
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


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        _logger.info("[%s] %s %s", request_id, request.method, request.url.path)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class BusinessCreate(BaseModel):
    legal_name: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default="America/New_York", min_length=1, max_length=60)
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default="US", max_length=100)


class BusinessResponse(BaseModel):
    id: int
    legal_name: str
    display_name: str
    timezone: str
    is_active: bool
    phone: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None


class BusinessUpdate(BaseModel):
    legal_name: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=100)
    timezone: str | None = Field(default=None, max_length=60)
    is_active: bool | None = None
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=100)


class CampaignCreate(BaseModel):
    campaign_name: str = Field(min_length=1, max_length=200)
    campaign_key: str | None = Field(default=None, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    objective: str | None = Field(default=None, max_length=1000)
    footnote_text: str | None = Field(default=None, max_length=2000)
    status: Literal["draft", "active", "paused", "completed", "archived"] = "draft"
    start_date: str | None = None
    end_date: str | None = None


class CampaignUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    objective: str | None = Field(default=None, max_length=1000)
    footnote_text: str | None = Field(default=None, max_length=2000)
    status: Literal["draft", "active", "paused", "completed", "archived"] | None = None
    start_date: str | None = None
    end_date: str | None = None


class CampaignCloneRequest(BaseModel):
    new_campaign_name: str = Field(min_length=1, max_length=200)
    campaign_key: str | None = Field(default=None, max_length=100)


class CampaignOfferCreate(BaseModel):
    offer_name: str = Field(min_length=1, max_length=200)
    offer_type: str = Field(default="discount", min_length=1, max_length=100)
    offer_value: str | None = Field(default=None, max_length=200)
    start_date: str | None = None
    end_date: str | None = None
    terms_text: str | None = Field(default=None, max_length=2000)


class CampaignAssetCreate(BaseModel):
    asset_type: str = Field(min_length=1, max_length=100)
    source_type: Literal["upload", "url", "generated"]
    mime_type: str = Field(min_length=1, max_length=100)
    source_path: str = Field(min_length=1, max_length=500)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] | None = None

    @field_validator("source_path")
    @classmethod
    def validate_no_path_traversal(cls, v: str) -> str:
        if ".." in Path(v).parts:
            raise ValueError("source_path must not contain path traversal sequences")
        return v

    @model_validator(mode="after")
    def validate_url_source(self) -> "CampaignAssetCreate":
        if self.source_type == "url":
            parsed = urlparse(self.source_path)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("source_path must be a valid http or https URL when source_type is url")
        return self


class TemplateDefinitionCreate(BaseModel):
    template_name: str = Field(min_length=1, max_length=200)
    template_kind: str = Field(min_length=1, max_length=100)
    size_spec: str | None = Field(default=None, max_length=50)
    layout: dict[str, Any] | None = None
    default_values: dict[str, Any] | None = None


class CampaignTemplateBindingCreate(BaseModel):
    template_id: int
    override_values: dict[str, Any] | None = None


class ChatMessageRequest(BaseModel):
    campaign_id: int | None = None
    message: str = Field(min_length=1, max_length=4000)


class ComponentCreate(BaseModel):
    component_key: str = Field(min_length=1, max_length=100)
    component_kind: str = Field(default="featured-offers", max_length=100)
    display_title: str = Field(min_length=1, max_length=200)
    render_region: str | None = Field(default=None, max_length=100)
    render_mode: str | None = Field(default=None, max_length=100)
    style: dict[str, Any] | None = None
    background_color: str | None = Field(default=None, max_length=100)
    header_accent_color: str | None = Field(default=None, max_length=100)
    footnote_text: str | None = Field(default=None, max_length=2000)
    subtitle: str | None = Field(default=None, max_length=1000)
    description_text: str | None = Field(default=None, max_length=4000)
    display_order: int = 0


class ComponentUpdate(BaseModel):
    component_key: str | None = Field(default=None, min_length=1, max_length=100)
    component_kind: str | None = Field(default=None, max_length=100)
    display_title: str | None = Field(default=None, min_length=1, max_length=200)
    render_region: str | None = Field(default=None, max_length=100)
    render_mode: str | None = Field(default=None, max_length=100)
    style: dict[str, Any] | None = None
    background_color: str | None = Field(default=None, max_length=100)
    header_accent_color: str | None = Field(default=None, max_length=100)
    footnote_text: str | None = Field(default=None, max_length=2000)
    subtitle: str | None = Field(default=None, max_length=1000)
    description_text: str | None = Field(default=None, max_length=4000)
    display_order: int | None = None


class ComponentItemCreate(BaseModel):
    item_name: str = Field(min_length=1, max_length=200)
    item_kind: str = Field(default="service", max_length=100)
    render_role: str | None = Field(default=None, max_length=100)
    style: dict[str, Any] | None = None
    duration_label: str | None = Field(default=None, max_length=200)
    item_value: str | None = Field(default=None, max_length=200)
    background_color: str | None = Field(default=None, max_length=100)
    description_text: str | None = Field(default=None, max_length=4000)
    terms_text: str | None = Field(default=None, max_length=2000)
    display_order: int = 0


class ComponentItemUpdate(BaseModel):
    item_name: str | None = Field(default=None, min_length=1, max_length=200)
    item_kind: str | None = Field(default=None, max_length=100)
    render_role: str | None = Field(default=None, max_length=100)
    style: dict[str, Any] | None = None
    duration_label: str | None = Field(default=None, max_length=200)
    item_value: str | None = Field(default=None, max_length=200)
    background_color: str | None = Field(default=None, max_length=100)
    description_text: str | None = Field(default=None, max_length=4000)
    terms_text: str | None = Field(default=None, max_length=2000)
    display_order: int | None = None


class CampaignSaveRequest(BaseModel):
    commit_message: str | None = Field(default=None, max_length=500)


class ArtifactRenderRequest(BaseModel):
    artifact_type: Literal["flyer", "poster"] = "flyer"
    overwrite: bool = False
    custom_name: str | None = Field(default=None, max_length=100)


class StartupResolveRequest(BaseModel):
    direction: Literal["yaml_to_db", "db_to_yaml", "skip"]


class ArtifactResponse(BaseModel):
    id: int
    campaign_id: int
    artifact_type: str
    file_path: str
    checksum: str
    status: str
    created_at: str | None = None


ALLOWED_ASSET_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "application/pdf",
    "text/plain",
}


def _require_business(connection: Any, business_id: int) -> None:
    row = connection.execute("SELECT id FROM businesses WHERE id = ?;", (business_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Business not found")


def _require_campaign(connection: Any, campaign_id: int) -> None:
    row = connection.execute("SELECT id FROM campaigns WHERE id = ?;", (campaign_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")


def _require_template(connection: Any, template_id: int) -> None:
    row = connection.execute("SELECT id FROM template_definitions WHERE id = ?;", (template_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")


def _require_component(connection: Any, component_id: int) -> None:
    row = connection.execute("SELECT id FROM campaign_components WHERE id = ?;", (component_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Component not found")


def _require_item(connection: Any, item_id: int) -> None:
    row = connection.execute("SELECT id FROM campaign_component_items WHERE id = ?;", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Component item not found")


def _parse_iso_date(value: str | None, field_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}; expected YYYY-MM-DD") from exc


def _offers_overlap(start_a: date | None, end_a: date | None, start_b: date | None, end_b: date | None) -> bool:
    if start_a is None or end_a is None or start_b is None or end_b is None:
        return False
    return start_a <= end_b and start_b <= end_a


def _campaign_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "business_id": row["business_id"],
        "campaign_name": row["campaign_name"],
        "campaign_key": row["campaign_key"] or None,
        "title": row["title"],
        "objective": row["objective"],
        "footnote_text": row["footnote_text"],
        "status": row["status"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
    }


def _campaign_display_name(row: Any) -> str:
    details = json.loads(row["details_json"] or "{}") if "details_json" in row.keys() else {}
    return details.get("display_name") or row["campaign_name"]


def _persist_campaign_yaml_or_raise(connection: Any, config: Any, campaign_id: int) -> tuple[Path, Path]:
    try:
        return persist_yaml_state_for_campaign(connection, config.data_dir, campaign_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def _business_snapshot(connection: Any, display_name: str) -> dict[str, Any]:
    business = connection.execute(
        """
        SELECT id, legal_name, display_name, timezone, is_active
        FROM businesses
        WHERE display_name = ?;
        """,
        (display_name,),
    ).fetchone()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    contacts = connection.execute(
        """
        SELECT contact_type, contact_value, is_primary
        FROM business_contacts
        WHERE business_id = ?
        ORDER BY is_primary DESC, id ASC;
        """,
        (business["id"],),
    ).fetchall()
    locations = connection.execute(
        """
        SELECT label, line1, line2, city, state, postal_code, country, hours_json
        FROM business_locations
        WHERE business_id = ?
        ORDER BY id ASC;
        """,
        (business["id"],),
    ).fetchall()
    theme = connection.execute(
        """
        SELECT name, primary_color, secondary_color, accent_color, font_family, logo_path
        FROM brand_themes
        WHERE business_id = ? AND name = 'default';
        """,
        (business["id"],),
    ).fetchone()

    return {
        "display_name": business["display_name"],
        "legal_name": business["legal_name"],
        "timezone": business["timezone"],
        "is_active": bool(business["is_active"]),
        "contacts": [
            {
                "contact_type": row["contact_type"],
                "contact_value": row["contact_value"],
                "is_primary": bool(row["is_primary"]),
            }
            for row in contacts
        ],
        "locations": [
            {
                "label": row["label"],
                "line1": row["line1"],
                "line2": row["line2"],
                "city": row["city"],
                "state": row["state"],
                "postal_code": row["postal_code"],
                "country": row["country"],
                "hours": json.loads(row["hours_json"] or "{}"),
            }
            for row in locations
        ],
        "brand_theme": {
            "name": theme["name"],
            "primary_color": theme["primary_color"],
            "secondary_color": theme["secondary_color"],
            "accent_color": theme["accent_color"],
            "font_family": theme["font_family"],
            "logo_path": theme["logo_path"],
        }
        if theme is not None
        else None,
    }


def _campaign_snapshot(connection: Any, display_name: str, campaign_name: str, qualifier: str | None) -> dict[str, Any]:
    business = connection.execute(
        "SELECT id FROM businesses WHERE display_name = ?;",
        (display_name,),
    ).fetchone()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    row = connection.execute(
        """
        SELECT id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date, details_json
        FROM campaigns
        WHERE business_id = ? AND campaign_name = ? AND campaign_key = ?;
        """,
        (business["id"], campaign_name, qualifier or ""),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    offers = connection.execute(
        """
        SELECT offer_name, offer_type, offer_value, start_date, end_date, terms_text
        FROM campaign_offers WHERE campaign_id = ? ORDER BY id ASC;
        """,
        (row["id"],),
    ).fetchall()
    assets = connection.execute(
        """
        SELECT asset_type, source_type, mime_type, source_path, width, height, metadata_json
        FROM campaign_assets WHERE campaign_id = ? ORDER BY id ASC;
        """,
        (row["id"],),
    ).fetchall()
    binding = connection.execute(
        """
        SELECT t.template_name, t.template_kind, t.size_spec, t.layout_json, t.default_values_json, b.override_values_json
        FROM campaign_template_bindings b
        JOIN template_definitions t ON t.id = b.template_id
        WHERE b.campaign_id = ? AND b.is_active = 1
        ORDER BY b.id DESC
        LIMIT 1;
        """,
        (row["id"],),
    ).fetchone()
    components = connection.execute(
        """
        SELECT id, component_key, component_kind, render_region, render_mode, style_json, display_title, footnote_text, subtitle, description_text, display_order
        FROM campaign_components
        WHERE campaign_id = ?
        ORDER BY display_order ASC, id ASC;
        """,
        (row["id"],),
    ).fetchall()

    component_payloads: list[dict[str, Any]] = []
    for component in components:
        items = connection.execute(
            """
            SELECT item_name, item_kind, duration_label, item_value, render_role, style_json, description_text, terms_text, display_order
            FROM campaign_component_items
            WHERE component_id = ?
            ORDER BY display_order ASC, id ASC;
            """,
            (component["id"],),
        ).fetchall()
        component_payloads.append(
            {
                "component_key": component["component_key"],
                "component_kind": component["component_kind"],
                "render_region": component["render_region"],
                "render_mode": component["render_mode"],
                "style": json.loads(component["style_json"] or "{}"),
                "display_title": component["display_title"],
                "footnote_text": component["footnote_text"],
                "subtitle": component["subtitle"],
                "description_text": component["description_text"],
                "display_order": component["display_order"],
                "items": [
                    {
                        "item_name": item["item_name"],
                        "item_kind": item["item_kind"],
                        "duration_label": item["duration_label"],
                        "item_value": item["item_value"],
                        "render_role": item["render_role"],
                        "style": json.loads(item["style_json"] or "{}"),
                        "description_text": item["description_text"],
                        "terms_text": item["terms_text"],
                        "display_order": item["display_order"],
                    }
                    for item in items
                ],
            }
        )

    return {
        "id": row["id"],
        "display_name": _campaign_display_name(row),
        "campaign_name": row["campaign_name"],
        "qualifier": row["campaign_key"] or None,
        "title": row["title"],
        "objective": row["objective"],
        "footnote_text": row["footnote_text"],
        "status": row["status"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "offers": [
            {
                "offer_name": item["offer_name"],
                "offer_type": item["offer_type"],
                "offer_value": item["offer_value"],
                "start_date": item["start_date"],
                "end_date": item["end_date"],
                "terms_text": item["terms_text"],
            }
            for item in offers
        ],
        "assets": [
            {
                "asset_type": item["asset_type"],
                "source_type": item["source_type"],
                "mime_type": item["mime_type"],
                "source_path": item["source_path"],
                "width": item["width"],
                "height": item["height"],
                "metadata": json.loads(item["metadata_json"] or "{}"),
            }
            for item in assets
        ],
        "components": component_payloads,
        "template_binding": {
            "template_name": binding["template_name"],
            "template_kind": binding["template_kind"],
            "size_spec": binding["size_spec"],
            "layout": json.loads(binding["layout_json"] or "{}"),
            "default_values": json.loads(binding["default_values_json"] or "{}"),
            "override_values": json.loads(binding["override_values_json"] or "{}"),
        }
        if binding is not None
        else None,
    }


def _business_select_sql() -> str:
        return """
                SELECT b.id, b.legal_name, b.display_name, b.timezone, b.is_active,
                             (
                                 SELECT contact_value
                                 FROM business_contacts bc
                                 WHERE bc.business_id = b.id AND bc.contact_type = 'phone'
                                 ORDER BY bc.is_primary DESC, bc.id ASC
                                 LIMIT 1
                             ) AS phone,
                             (
                                 SELECT line1
                                 FROM business_locations bl
                                 WHERE bl.business_id = b.id
                                 ORDER BY bl.id ASC
                                 LIMIT 1
                             ) AS address_line1,
                             (
                                 SELECT line2
                                 FROM business_locations bl
                                 WHERE bl.business_id = b.id
                                 ORDER BY bl.id ASC
                                 LIMIT 1
                             ) AS address_line2,
                             (
                                 SELECT city
                                 FROM business_locations bl
                                 WHERE bl.business_id = b.id
                                 ORDER BY bl.id ASC
                                 LIMIT 1
                             ) AS city,
                             (
                                 SELECT state
                                 FROM business_locations bl
                                 WHERE bl.business_id = b.id
                                 ORDER BY bl.id ASC
                                 LIMIT 1
                             ) AS state,
                             (
                                 SELECT postal_code
                                 FROM business_locations bl
                                 WHERE bl.business_id = b.id
                                 ORDER BY bl.id ASC
                                 LIMIT 1
                             ) AS postal_code,
                             (
                                 SELECT country
                                 FROM business_locations bl
                                 WHERE bl.business_id = b.id
                                 ORDER BY bl.id ASC
                                 LIMIT 1
                             ) AS country
                FROM businesses b
        """


def _business_row_to_response(row: Any) -> BusinessResponse:
        return BusinessResponse(
                id=row["id"],
                legal_name=row["legal_name"],
                display_name=row["display_name"],
                timezone=row["timezone"],
                is_active=bool(row["is_active"]),
                phone=row["phone"],
                address_line1=row["address_line1"],
                address_line2=row["address_line2"],
                city=row["city"],
                state=row["state"],
                postal_code=row["postal_code"],
                country=row["country"],
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
    def health() -> dict[str, str]:
        config = resolve_config()
        with connect_database(config) as connection:
            connection.execute("SELECT 1;")

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
        with connect_database(config) as connection:
            if request.direction == "yaml_to_db":
                sync_data_directory(connection, config.data_dir)
                connection.commit()
            elif request.direction == "db_to_yaml":
                write_all_to_data_dir(connection, config.data_dir)
                connection.commit()
            # "skip" → no data changes
        _reconciliation["needed"] = False
        _reconciliation["report"] = None
        return {"ok": True}

    @app.post("/businesses", response_model=BusinessResponse, status_code=201)
    def create_business(payload: BusinessCreate) -> BusinessResponse:
        phone = (payload.phone or "").strip()
        address_line1 = (payload.address_line1 or "").strip()
        address_line2 = (payload.address_line2 or "").strip()
        city = (payload.city or "").strip()
        state = (payload.state or "").strip()
        postal_code = (payload.postal_code or "").strip()
        country = (payload.country or "US").strip() or "US"

        has_any_address = any((address_line1, address_line2, city, state, postal_code))
        has_required_address = all((address_line1, city, state, postal_code))
        if has_any_address and not has_required_address:
            raise HTTPException(
                status_code=400,
                detail="Address requires address_line1, city, state, and postal_code",
            )

        config = resolve_config()
        with connect_database(config) as connection:
            cursor = connection.execute(
                """
                INSERT INTO businesses (legal_name, display_name, timezone)
                VALUES (?, ?, ?);
                """,
                (payload.legal_name.strip(), payload.display_name.strip(), payload.timezone.strip()),
            )
            business_id = int(cursor.lastrowid)

            if phone:
                connection.execute(
                    """
                    INSERT INTO business_contacts (business_id, contact_type, contact_value, is_primary)
                    VALUES (?, 'phone', ?, 1);
                    """,
                    (business_id, phone),
                )

            if has_required_address:
                connection.execute(
                    """
                    INSERT INTO business_locations (
                      business_id, label, line1, line2, city, state, postal_code, country, hours_json
                    )
                    VALUES (?, NULL, ?, ?, ?, ?, ?, ?, '{}');
                    """,
                    (
                        business_id,
                        address_line1,
                        address_line2 or None,
                        city,
                        state,
                        postal_code,
                        country,
                    ),
                )

            row = connection.execute(
                _business_select_sql() + " WHERE b.id = ?;",
                (business_id,),
            ).fetchone()
            connection.commit()

        if row is None:
            raise HTTPException(status_code=500, detail="Business creation failed")

        return _business_row_to_response(row)

    @app.get("/businesses", response_model=list[BusinessResponse])
    def list_businesses() -> list[BusinessResponse]:
        config = resolve_config()
        with connect_database(config) as connection:
            rows = connection.execute(
                _business_select_sql() + " ORDER BY b.id ASC;"
            ).fetchall()

        return [_business_row_to_response(row) for row in rows]

    @app.get("/businesses/{business_id}", response_model=BusinessResponse)
    def get_business(business_id: int) -> BusinessResponse:
        config = resolve_config()
        with connect_database(config) as connection:
            row = connection.execute(
                _business_select_sql() + " WHERE b.id = ?;",
                (business_id,),
            ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Business not found")

        return _business_row_to_response(row)

    @app.patch("/businesses/{business_id}", response_model=BusinessResponse)
    def update_business(business_id: int, payload: BusinessUpdate) -> BusinessResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No business fields provided")

        location_fields = {"address_line1", "address_line2", "city", "state", "postal_code", "country"}
        location_updates: dict[str, str] = {}
        for field in list(location_fields):
            if field in updates:
                location_updates[field] = str(updates.pop(field) or "").strip()

        phone_update = None
        if "phone" in updates:
            phone_update = str(updates.pop("phone") or "").strip()

        for field in ("legal_name", "display_name", "timezone"):
            if field in updates:
                value = str(updates[field]).strip()
                if value == "":
                    raise HTTPException(status_code=400, detail=f"{field} cannot be empty")
                updates[field] = value

        config = resolve_config()
        with connect_database(config) as connection:
            existing = connection.execute(
                _business_select_sql() + " WHERE b.id = ?;",
                (business_id,),
            ).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="Business not found")

            if updates:
                fields_sql = ", ".join([f"{field} = ?" for field in updates.keys()])
                values = list(updates.values()) + [business_id]
                try:
                    connection.execute(
                        f"UPDATE businesses SET {fields_sql}, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                        values,
                    )
                except sqlite3.IntegrityError as error:
                    raise HTTPException(status_code=409, detail="Business update conflicts with existing data") from error

            if phone_update is not None:
                connection.execute(
                    "DELETE FROM business_contacts WHERE business_id = ? AND contact_type = 'phone';",
                    (business_id,),
                )
                if phone_update:
                    connection.execute(
                        """
                        INSERT INTO business_contacts (business_id, contact_type, contact_value, is_primary)
                        VALUES (?, 'phone', ?, 1);
                        """,
                        (business_id, phone_update),
                    )

            if location_updates:
                current_line1 = (existing["address_line1"] or "").strip()
                current_city = (existing["city"] or "").strip()
                current_state = (existing["state"] or "").strip()
                current_postal = (existing["postal_code"] or "").strip()
                current_line2 = (existing["address_line2"] or "").strip()
                current_country = (existing["country"] or "US").strip() or "US"

                next_line1 = location_updates.get("address_line1", current_line1)
                next_city = location_updates.get("city", current_city)
                next_state = location_updates.get("state", current_state)
                next_postal = location_updates.get("postal_code", current_postal)
                next_line2 = location_updates.get("address_line2", current_line2)
                next_country = location_updates.get("country", current_country) or "US"

                required = (next_line1, next_city, next_state, next_postal)
                has_any = any((next_line1, next_line2, next_city, next_state, next_postal))
                if has_any and not all(required):
                    raise HTTPException(
                        status_code=400,
                        detail="Address requires address_line1, city, state, and postal_code",
                    )

                connection.execute(
                    "DELETE FROM business_locations WHERE business_id = ?;",
                    (business_id,),
                )
                if all(required):
                    connection.execute(
                        """
                        INSERT INTO business_locations (
                          business_id, label, line1, line2, city, state, postal_code, country, hours_json
                        )
                        VALUES (?, NULL, ?, ?, ?, ?, ?, ?, '{}');
                        """,
                        (
                            business_id,
                            next_line1,
                            next_line2 or None,
                            next_city,
                            next_state,
                            next_postal,
                            next_country,
                        ),
                    )

            row = connection.execute(
                _business_select_sql() + " WHERE b.id = ?;",
                (business_id,),
            ).fetchone()

            campaign_rows = connection.execute(
                "SELECT id FROM campaigns WHERE business_id = ? ORDER BY id ASC;",
                (business_id,),
            ).fetchall()
            for campaign in campaign_rows:
                _persist_campaign_yaml_or_raise(connection, config, campaign["id"])
            connection.commit()

        if row is None:
            raise HTTPException(status_code=500, detail="Business update failed")

        return _business_row_to_response(row)

    @app.get("/businesses/{business_id}/campaigns/lookup")
    def lookup_campaigns_by_name(business_id: int, campaign_name: str) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_business(connection, business_id)
            rows = connection.execute(
                """
                SELECT id, business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date
                FROM campaigns
                WHERE business_id = ? AND campaign_name = ?
                ORDER BY id ASC;
                """,
                (business_id, campaign_name.strip()),
            ).fetchall()

        return {
            "campaign_name": campaign_name.strip(),
            "matches": [_campaign_row_to_dict(row) for row in rows],
            "prompt": "open_existing_or_create_new" if rows else "create_new",
        }

    @app.post("/businesses/{business_id}/campaigns", status_code=201)
    def create_campaign(business_id: int, payload: CampaignCreate) -> dict[str, Any]:
        normalized_name = payload.campaign_name.strip()
        normalized_key = (payload.campaign_key or "").strip()
        if normalized_key.lower() == "none":
            normalized_key = ""

        config = resolve_config()
        with connect_database(config) as connection:
            _require_business(connection, business_id)

            name_matches = connection.execute(
                """
                SELECT id, business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date
                FROM campaigns
                WHERE business_id = ? AND campaign_name = ?
                ORDER BY id ASC;
                """,
                (business_id, normalized_name),
            ).fetchall()

            if name_matches and normalized_key == "":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Campaign name already exists. Choose an existing campaign or provide campaign_key to create a new one.",
                        "resolution": "open_existing_or_create_new",
                        "matches": [_campaign_row_to_dict(row) for row in name_matches],
                    },
                )

            duplicate_key_row = connection.execute(
                """
                SELECT id
                FROM campaigns
                WHERE business_id = ? AND campaign_name = ? AND campaign_key = ?;
                """,
                (business_id, normalized_name, normalized_key),
            ).fetchone()
            if duplicate_key_row is not None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Campaign with the same name and key already exists.",
                        "resolution": "open_existing",
                    },
                )

            cursor = connection.execute(
                """
                INSERT INTO campaigns (
                  business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    business_id,
                    normalized_name,
                    normalized_key,
                    payload.title.strip(),
                    payload.objective,
                    payload.footnote_text,
                    payload.status,
                    payload.start_date,
                    payload.end_date,
                ),
            )
            campaign_id = int(cursor.lastrowid)
            row = connection.execute(
                """
                SELECT id, business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date
                FROM campaigns
                WHERE id = ?;
                """,
                (campaign_id,),
            ).fetchone()
            _persist_campaign_yaml_or_raise(connection, config, campaign_id)
            connection.commit()

        if row is None:
            raise HTTPException(status_code=500, detail="Campaign creation failed")
        return _campaign_row_to_dict(row)

    @app.patch("/businesses/{business_id}/campaigns/{campaign_id}")
    def update_campaign(business_id: int, campaign_id: int, payload: CampaignUpdate) -> dict[str, Any]:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No campaign fields provided")

        if "title" in updates and isinstance(updates["title"], str):
            updates["title"] = updates["title"].strip()
            if updates["title"] == "":
                raise HTTPException(status_code=400, detail="title cannot be empty")

        config = resolve_config()
        with connect_database(config) as connection:
            _require_business(connection, business_id)

            existing = connection.execute(
                """
                SELECT id, business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date
                FROM campaigns
                WHERE id = ? AND business_id = ?;
                """,
                (campaign_id, business_id),
            ).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="Campaign not found")

            fields_sql = ", ".join([f"{field} = ?" for field in updates.keys()])
            values = list(updates.values()) + [campaign_id, business_id]
            connection.execute(
                f"UPDATE campaigns SET {fields_sql}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND business_id = ?;",
                values,
            )

            updated = connection.execute(
                """
                SELECT id, business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date
                FROM campaigns
                WHERE id = ?;
                """,
                (campaign_id,),
            ).fetchone()
            _persist_campaign_yaml_or_raise(connection, config, campaign_id)
            connection.commit()

        if updated is None:
            raise HTTPException(status_code=500, detail="Campaign update failed")
        return _campaign_row_to_dict(updated)

    @app.post("/businesses/{business_id}/campaigns/{campaign_id}/clone", status_code=201)
    def clone_campaign(business_id: int, campaign_id: int, payload: CampaignCloneRequest) -> dict[str, Any]:
        new_name = payload.new_campaign_name.strip()
        new_key = (payload.campaign_key or "").strip()
        if new_name == "":
            raise HTTPException(status_code=400, detail="new_campaign_name cannot be empty")

        config = resolve_config()
        with connect_database(config) as connection:
            _require_business(connection, business_id)
            source = connection.execute(
                """
                SELECT c.id, c.business_id, c.campaign_name, c.campaign_key, b.display_name AS business_display_name
                FROM campaigns c
                JOIN businesses b ON b.id = c.business_id
                WHERE c.id = ? AND c.business_id = ?;
                """,
                (campaign_id, business_id),
            ).fetchone()
            if source is None:
                raise HTTPException(status_code=404, detail="Campaign not found")

            name_matches = connection.execute(
                """
                SELECT id, campaign_key
                FROM campaigns
                WHERE business_id = ? AND campaign_name = ?
                ORDER BY id ASC;
                """,
                (business_id, new_name),
            ).fetchall()
            if name_matches and new_key == "":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Campaign name already exists. Provide campaign_key to make it unique.",
                        "resolution": "provide_secondary_key",
                        "matches": [
                            {"id": row["id"], "campaign_key": row["campaign_key"] or None}
                            for row in name_matches
                        ],
                    },
                )

            duplicate = connection.execute(
                """
                SELECT id
                FROM campaigns
                WHERE business_id = ? AND campaign_name = ? AND campaign_key = ?;
                """,
                (business_id, new_name, new_key),
            ).fetchone()
            if duplicate is not None:
                raise HTTPException(status_code=409, detail="Campaign name and secondary key already exist")

            destination_slug = new_name if new_key == "" else f"{new_name}-{new_key}"
            try:
                record = clone_campaign_directory(
                    connection,
                    config.data_dir,
                    source_campaign_name=source["campaign_name"],
                    source_campaign_key=source["campaign_key"] or "",
                    new_campaign_name=new_name,
                    new_campaign_key=new_key or None,
                    destination_directory_name=destination_slug,
                    business_name=source["business_display_name"],
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            row = connection.execute(
                """
                SELECT id, business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date
                FROM campaigns
                WHERE business_id = ? AND campaign_name = ? AND campaign_key = ?
                ORDER BY id DESC
                LIMIT 1;
                """,
                (business_id, record.payload.get("campaign_name"), record.payload.get("qualifier") or ""),
            ).fetchone()
            connection.commit()

        if row is None:
            raise HTTPException(status_code=500, detail="Campaign clone failed")
        return _campaign_row_to_dict(row)

    @app.get("/businesses/{business_id}/campaigns")
    def list_campaigns(business_id: int) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_business(connection, business_id)
            rows = connection.execute(
                """
                SELECT id, business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date
                FROM campaigns
                WHERE business_id = ?
                ORDER BY campaign_name ASC, campaign_key ASC, id ASC;
                """,
                (business_id,),
            ).fetchall()

        return {"items": [_campaign_row_to_dict(row) for row in rows]}

    @app.get("/businesses/{business_id}/campaigns/{campaign_id}")
    def get_campaign(business_id: int, campaign_id: int) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_business(connection, business_id)
            row = connection.execute(
                """
                SELECT id, business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date
                FROM campaigns
                WHERE id = ? AND business_id = ?;
                """,
                (campaign_id, business_id),
            ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return _campaign_row_to_dict(row)

    @app.post("/campaigns/{campaign_id}/offers", status_code=201)
    def create_campaign_offer(campaign_id: int, payload: CampaignOfferCreate) -> dict[str, Any]:
        new_start = _parse_iso_date(payload.start_date, "start_date")
        new_end = _parse_iso_date(payload.end_date, "end_date")
        if (new_start is None) != (new_end is None):
            raise HTTPException(status_code=400, detail="Offer requires both start_date and end_date when scheduling")
        if new_start is not None and new_end is not None and new_start > new_end:
            raise HTTPException(status_code=400, detail="Offer start_date cannot be after end_date")

        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)

            existing_rows = connection.execute(
                """
                SELECT id, start_date, end_date
                FROM campaign_offers
                WHERE campaign_id = ?;
                """,
                (campaign_id,),
            ).fetchall()
            for row in existing_rows:
                existing_start = _parse_iso_date(row["start_date"], "start_date")
                existing_end = _parse_iso_date(row["end_date"], "end_date")
                if _offers_overlap(new_start, new_end, existing_start, existing_end):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "Offer date window overlaps with an existing offer",
                            "existing_offer_id": row["id"],
                        },
                    )

            cursor = connection.execute(
                """
                INSERT INTO campaign_offers (
                  campaign_id, offer_name, offer_type, offer_value, start_date, end_date, terms_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    campaign_id,
                    payload.offer_name.strip(),
                    payload.offer_type.strip(),
                    payload.offer_value,
                    payload.start_date,
                    payload.end_date,
                    payload.terms_text,
                ),
            )
            offer_id = int(cursor.lastrowid)
            row = connection.execute(
                """
                SELECT id, campaign_id, offer_name, offer_type, offer_value, start_date, end_date, terms_text
                FROM campaign_offers
                WHERE id = ?;
                """,
                (offer_id,),
            ).fetchone()
            _persist_campaign_yaml_or_raise(connection, config, campaign_id)
            connection.commit()

        if row is None:
            raise HTTPException(status_code=500, detail="Offer creation failed")
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "offer_name": row["offer_name"],
            "offer_type": row["offer_type"],
            "offer_value": row["offer_value"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "terms_text": row["terms_text"],
        }

    @app.get("/campaigns/{campaign_id}/offers")
    def list_campaign_offers(campaign_id: int) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            rows = connection.execute(
                """
                SELECT id, campaign_id, offer_name, offer_type, offer_value, start_date, end_date, terms_text
                FROM campaign_offers
                WHERE campaign_id = ?
                ORDER BY start_date ASC, id ASC;
                """,
                (campaign_id,),
            ).fetchall()

        return {
            "items": [
                {
                    "id": row["id"],
                    "campaign_id": row["campaign_id"],
                    "offer_name": row["offer_name"],
                    "offer_type": row["offer_type"],
                    "offer_value": row["offer_value"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "terms_text": row["terms_text"],
                }
                for row in rows
            ]
        }

    @app.post("/campaigns/{campaign_id}/assets", status_code=201)
    def create_campaign_asset(campaign_id: int, payload: CampaignAssetCreate) -> dict[str, Any]:
        mime_type = payload.mime_type.strip().lower()
        if mime_type not in ALLOWED_ASSET_MIME_TYPES:
            raise HTTPException(status_code=400, detail="Unsupported mime_type")

        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            cursor = connection.execute(
                """
                INSERT INTO campaign_assets (
                  campaign_id, asset_type, source_type, mime_type, source_path, width, height, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    campaign_id,
                    payload.asset_type.strip(),
                    payload.source_type,
                    mime_type,
                    payload.source_path.strip(),
                    payload.width,
                    payload.height,
                    json.dumps(payload.metadata or {}),
                ),
            )
            asset_id = int(cursor.lastrowid)
            row = connection.execute(
                """
                SELECT id, campaign_id, asset_type, source_type, mime_type, source_path, width, height, metadata_json
                FROM campaign_assets
                WHERE id = ?;
                """,
                (asset_id,),
            ).fetchone()
            _persist_campaign_yaml_or_raise(connection, config, campaign_id)
            connection.commit()

        if row is None:
            raise HTTPException(status_code=500, detail="Asset creation failed")
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "asset_type": row["asset_type"],
            "source_type": row["source_type"],
            "mime_type": row["mime_type"],
            "source_path": row["source_path"],
            "width": row["width"],
            "height": row["height"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
        }

    @app.get("/campaigns/{campaign_id}/assets")
    def list_campaign_assets(campaign_id: int) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            rows = connection.execute(
                """
                SELECT id, campaign_id, asset_type, source_type, mime_type, source_path, width, height, metadata_json
                FROM campaign_assets
                WHERE campaign_id = ?
                ORDER BY id ASC;
                """,
                (campaign_id,),
            ).fetchall()

        return {
            "items": [
                {
                    "id": row["id"],
                    "campaign_id": row["campaign_id"],
                    "asset_type": row["asset_type"],
                    "source_type": row["source_type"],
                    "mime_type": row["mime_type"],
                    "source_path": row["source_path"],
                    "width": row["width"],
                    "height": row["height"],
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                }
                for row in rows
            ]
        }

    @app.post("/templates", status_code=201)
    def create_template(payload: TemplateDefinitionCreate) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            duplicate = connection.execute(
                "SELECT id FROM template_definitions WHERE template_name = ?;",
                (payload.template_name.strip(),),
            ).fetchone()
            if duplicate is not None:
                raise HTTPException(status_code=409, detail="Template name already exists")

            cursor = connection.execute(
                """
                INSERT INTO template_definitions (
                  template_name, template_kind, size_spec, layout_json, default_values_json
                )
                VALUES (?, ?, ?, ?, ?);
                """,
                (
                    payload.template_name.strip(),
                    payload.template_kind.strip(),
                    payload.size_spec,
                    json.dumps(payload.layout or {}),
                    json.dumps(payload.default_values or {}),
                ),
            )
            template_id = int(cursor.lastrowid)
            row = connection.execute(
                """
                SELECT id, template_name, template_kind, size_spec, layout_json, default_values_json
                FROM template_definitions
                WHERE id = ?;
                """,
                (template_id,),
            ).fetchone()
            connection.commit()

        if row is None:
            raise HTTPException(status_code=500, detail="Template creation failed")
        return {
            "id": row["id"],
            "template_name": row["template_name"],
            "template_kind": row["template_kind"],
            "size_spec": row["size_spec"],
            "layout": json.loads(row["layout_json"] or "{}"),
            "default_values": json.loads(row["default_values_json"] or "{}"),
        }

    @app.get("/templates")
    def list_templates() -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            rows = connection.execute(
                """
                SELECT id, template_name, template_kind, size_spec, layout_json, default_values_json
                FROM template_definitions
                ORDER BY template_name ASC;
                """
            ).fetchall()

        return {
            "items": [
                {
                    "id": row["id"],
                    "template_name": row["template_name"],
                    "template_kind": row["template_kind"],
                    "size_spec": row["size_spec"],
                    "layout": json.loads(row["layout_json"] or "{}"),
                    "default_values": json.loads(row["default_values_json"] or "{}"),
                }
                for row in rows
            ]
        }

    @app.post("/campaigns/{campaign_id}/template-bindings", status_code=201)
    def create_template_binding(campaign_id: int, payload: CampaignTemplateBindingCreate) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            _require_template(connection, payload.template_id)

            connection.execute(
                "UPDATE campaign_template_bindings SET is_active = 0 WHERE campaign_id = ?;",
                (campaign_id,),
            )
            cursor = connection.execute(
                """
                INSERT INTO campaign_template_bindings (
                  campaign_id, template_id, override_values_json, is_active
                )
                VALUES (?, ?, ?, 1);
                """,
                (campaign_id, payload.template_id, json.dumps(payload.override_values or {})),
            )
            binding_id = int(cursor.lastrowid)

            row = connection.execute(
                """
                SELECT b.id, b.campaign_id, b.template_id, b.override_values_json, b.is_active,
                       t.template_name, t.template_kind, t.size_spec, t.layout_json, t.default_values_json
                FROM campaign_template_bindings b
                JOIN template_definitions t ON t.id = b.template_id
                WHERE b.id = ?;
                """,
                (binding_id,),
            ).fetchone()
            _persist_campaign_yaml_or_raise(connection, config, campaign_id)
            connection.commit()

        if row is None:
            raise HTTPException(status_code=500, detail="Template binding creation failed")
        defaults = json.loads(row["default_values_json"] or "{}")
        overrides = json.loads(row["override_values_json"] or "{}")
        effective_values = {**defaults, **overrides}

        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "template_id": row["template_id"],
            "template_name": row["template_name"],
            "template_kind": row["template_kind"],
            "size_spec": row["size_spec"],
            "layout": json.loads(row["layout_json"] or "{}"),
            "default_values": defaults,
            "override_values": overrides,
            "effective_values": effective_values,
            "is_active": bool(row["is_active"]),
        }

    @app.get("/campaigns/{campaign_id}/template-binding/effective")
    def get_effective_template_binding(campaign_id: int) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)

            row = connection.execute(
                """
                SELECT b.id, b.campaign_id, b.template_id, b.override_values_json, b.is_active,
                       t.template_name, t.template_kind, t.size_spec, t.layout_json, t.default_values_json
                FROM campaign_template_bindings b
                JOIN template_definitions t ON t.id = b.template_id
                WHERE b.campaign_id = ? AND b.is_active = 1
                ORDER BY b.id DESC
                LIMIT 1;
                """,
                (campaign_id,),
            ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="No active template binding for campaign")

        defaults = json.loads(row["default_values_json"] or "{}")
        overrides = json.loads(row["override_values_json"] or "{}")
        effective_values = {**defaults, **overrides}
        return {
            "id": row["id"],
            "campaign_id": row["campaign_id"],
            "template_id": row["template_id"],
            "template_name": row["template_name"],
            "template_kind": row["template_kind"],
            "size_spec": row["size_spec"],
            "layout": json.loads(row["layout_json"] or "{}"),
            "default_values": defaults,
            "override_values": overrides,
            "effective_values": effective_values,
            "is_active": bool(row["is_active"]),
        }

    @app.get("/campaigns/{campaign_id}/components")
    def list_campaign_components(campaign_id: int) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            rows = connection.execute(
                """
                SELECT id, component_key, component_kind, render_region, render_mode, style_json, display_title, subtitle,
                       description_text, footnote_text, background_color, header_accent_color, display_order
                FROM campaign_components
                WHERE campaign_id = ?
                ORDER BY display_order ASC, id ASC;
                """,
                (campaign_id,),
            ).fetchall()

            items_tree: list[dict[str, Any]] = []
            for r in rows:
                item_rows = connection.execute(
                    """
                    SELECT id, item_name, item_kind, duration_label, item_value, background_color, render_role, style_json, description_text, terms_text, display_order
                    FROM campaign_component_items
                    WHERE component_id = ?
                    ORDER BY display_order ASC, id ASC;
                    """,
                    (r["id"],),
                ).fetchall()
                items_tree.append(
                    {
                        "id": r["id"],
                        "component_key": r["component_key"],
                        "component_kind": r["component_kind"],
                        "render_region": r["render_region"],
                        "render_mode": r["render_mode"],
                        "style": json.loads(r["style_json"] or "{}"),
                        "display_title": r["display_title"],
                        "subtitle": r["subtitle"],
                        "description_text": r["description_text"],
                        "footnote_text": r["footnote_text"],
                        "background_color": r["background_color"],
                        "header_accent_color": r["header_accent_color"],
                        "display_order": r["display_order"],
                        "items": [
                            {
                                "id": ir["id"],
                                "item_name": ir["item_name"],
                                "item_kind": ir["item_kind"],
                                "duration_label": ir["duration_label"],
                                "item_value": ir["item_value"],
                                "background_color": ir["background_color"],
                                "render_role": ir["render_role"],
                                "style": json.loads(ir["style_json"] or "{}"),
                                "description_text": ir["description_text"],
                                "terms_text": ir["terms_text"],
                                "display_order": ir["display_order"],
                            }
                            for ir in item_rows
                        ],
                    }
                )
        return {
            "campaign_id": campaign_id,
            "items": items_tree,
        }

    @app.post("/campaigns/{campaign_id}/components", status_code=201)
    def create_component(campaign_id: int, payload: ComponentCreate) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO campaign_components (
                      campaign_id, component_key, component_kind, render_region, render_mode,
                      style_json, display_title, background_color, header_accent_color,
                      footnote_text, subtitle, description_text, display_order
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        campaign_id,
                        payload.component_key.strip(),
                        payload.component_kind.strip(),
                        payload.render_region,
                        payload.render_mode,
                        json.dumps(payload.style or {}),
                        payload.display_title.strip(),
                        payload.background_color,
                        payload.header_accent_color,
                        payload.footnote_text,
                        payload.subtitle,
                        payload.description_text,
                        payload.display_order,
                    ),
                )
                component_id = int(cursor.lastrowid)
                _persist_campaign_yaml_or_raise(connection, config, campaign_id)
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="Component key already exists in this campaign") from exc

        return {"id": component_id, "campaign_id": campaign_id, **payload.model_dump()}

    @app.patch("/campaigns/{campaign_id}/components/{component_id}")
    def update_component(campaign_id: int, component_id: int, payload: ComponentUpdate) -> dict[str, Any]:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No component fields provided")

        if "style" in updates:
            updates["style_json"] = json.dumps(updates.pop("style"))

        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            _require_component(connection, component_id)

            fields_sql = ", ".join([f"{field} = ?" for field in updates.keys()])
            values = list(updates.values()) + [component_id, campaign_id]
            try:
                connection.execute(
                    f"UPDATE campaign_components SET {fields_sql}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND campaign_id = ?;",
                    values,
                )
                _persist_campaign_yaml_or_raise(connection, config, campaign_id)
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="Component update conflicts with existing data") from exc

        return {"id": component_id, "campaign_id": campaign_id, "updates": list(updates.keys())}

    @app.delete("/campaigns/{campaign_id}/components/{component_id}", status_code=204)
    def delete_component(campaign_id: int, component_id: int) -> None:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            _require_component(connection, component_id)
            connection.execute("DELETE FROM campaign_components WHERE id = ? AND campaign_id = ?;", (component_id, campaign_id))
            _persist_campaign_yaml_or_raise(connection, config, campaign_id)
            connection.commit()

    @app.post("/campaigns/{campaign_id}/components/{component_id}/items", status_code=201)
    def create_component_item(campaign_id: int, component_id: int, payload: ComponentItemCreate) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            _require_component(connection, component_id)

            cursor = connection.execute(
                """
                INSERT INTO campaign_component_items (
                  component_id, item_name, item_kind, render_role, style_json,
                  duration_label, item_value, background_color, description_text,
                  terms_text, display_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    component_id,
                    payload.item_name.strip(),
                    payload.item_kind.strip(),
                    payload.render_role,
                    json.dumps(payload.style or {}),
                    payload.duration_label,
                    payload.item_value,
                    payload.background_color,
                    payload.description_text,
                    payload.terms_text,
                    payload.display_order,
                ),
            )
            item_id = int(cursor.lastrowid)
            _persist_campaign_yaml_or_raise(connection, config, campaign_id)
            connection.commit()

        return {"id": item_id, "component_id": component_id, **payload.model_dump()}

    @app.patch("/campaigns/{campaign_id}/components/{component_id}/items/{item_id}")
    def update_component_item(campaign_id: int, component_id: int, item_id: int, payload: ComponentItemUpdate) -> dict[str, Any]:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No item fields provided")

        if "style" in updates:
            updates["style_json"] = json.dumps(updates.pop("style"))

        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            _require_component(connection, component_id)
            _require_item(connection, item_id)

            fields_sql = ", ".join([f"{field} = ?" for field in updates.keys()])
            values = list(updates.values()) + [item_id, component_id]
            connection.execute(
                f"UPDATE campaign_component_items SET {fields_sql}, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND component_id = ?;",
                values,
            )
            _persist_campaign_yaml_or_raise(connection, config, campaign_id)
            connection.commit()

        return {"id": item_id, "component_id": component_id, "updates": list(updates.keys())}

    @app.delete("/campaigns/{campaign_id}/components/{component_id}/items/{item_id}", status_code=204)
    def delete_component_item(campaign_id: int, component_id: int, item_id: int) -> None:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            _require_component(connection, component_id)
            _require_item(connection, item_id)
            connection.execute("DELETE FROM campaign_component_items WHERE id = ? AND component_id = ?;", (item_id, component_id))
            _persist_campaign_yaml_or_raise(connection, config, campaign_id)
            connection.commit()

    @app.post("/chat/sessions", status_code=201)
    def create_chat_session() -> dict[str, str]:
        return {"session_id": chat_store.create()}

    @app.get("/chat/sessions/{session_id}")
    def get_chat_session_history(session_id: str) -> dict[str, Any]:
        if not chat_store.exists(session_id):
            raise HTTPException(status_code=404, detail="Chat session not found")
        return {"session_id": session_id, "history": chat_store.history(session_id)}

    @app.post("/chat/sessions/{session_id}/messages")
    def post_chat_message(session_id: str, payload: ChatMessageRequest) -> dict[str, Any]:
        if not chat_store.exists(session_id):
            raise HTTPException(status_code=404, detail="Chat session not found")

        def _sync_active_campaign_context(active_campaign_id: int | None) -> None:
            previous_campaign_id = chat_store.get_context(session_id).get("active_campaign_id")
            if previous_campaign_id != active_campaign_id:
                chat_store.set_context_value(session_id, "active_component_ref", None)
            chat_store.set_context_value(session_id, "active_campaign_id", active_campaign_id)

        clone_cmd = parse_clone_command(payload.message)
        if clone_cmd is not None:
            config = resolve_config()
            with connect_database(config) as connection:
                try:
                    record = clone_campaign_directory(
                        connection,
                        config.data_dir,
                        source_campaign_name=clone_cmd.source_campaign_name,
                        new_campaign_name=clone_cmd.new_campaign_name,
                        business_name=clone_cmd.business_name,
                    )
                    # Resolve the new campaign's DB id and business id
                    new_row = connection.execute(
                        """
                        SELECT c.id AS campaign_id, c.business_id
                        FROM campaigns c
                        WHERE c.campaign_name = ?
                        ORDER BY c.id DESC
                        LIMIT 1;
                        """,
                        (clone_cmd.new_campaign_name,),
                    ).fetchone()
                    connection.commit()
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc

            new_campaign_id = int(new_row["campaign_id"]) if new_row else None
            new_business_id = int(new_row["business_id"]) if new_row else None
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

        config = resolve_config()
        with connect_database(config) as connection:
            campaign_meta = connection.execute(
                """
                SELECT b.display_name AS business_display_name
                FROM campaigns c
                JOIN businesses b ON b.id = c.business_id
                WHERE c.id = ?;
                """,
                (payload.campaign_id,),
            ).fetchone()
            if campaign_meta is None:
                raise HTTPException(status_code=404, detail="Campaign not found")
            business_display_name = campaign_meta["business_display_name"]

        context_cmd = parse_session_context_command(payload.message)
        if context_cmd is not None:
            config = resolve_config()
            with connect_database(config) as connection:
                component = resolve_component(connection, payload.campaign_id, context_cmd.component_ref)
                if component is None:
                    raise HTTPException(status_code=404, detail="Component not found")
            chat_store.set_context_value(session_id, "active_component_ref", component["component_key"])
            chat_store.append(session_id, "user", payload.message)
            chat_store.append(
                session_id,
                "system",
                f"Set active component context to '{component['component_key']}'",
            )
            return {
                "session_id": session_id,
                "result": {
                    "target": "context",
                    "context_type": "component",
                    "component": {
                        "id": component["id"],
                        "campaign_id": component["campaign_id"],
                        "component_key": component["component_key"],
                        "component_kind": component["component_kind"],
                        "display_title": component["display_title"],
                    },
                    "message": f"Working on component {component['component_key']}",
                },
                "history": chat_store.history(session_id),
            }

        query_cmd = parse_query_command(payload.message)
        if query_cmd is not None:
            config = resolve_config()
            session_context = chat_store.get_context(session_id)
            with connect_database(config) as connection:
                if query_cmd.query_type == "list_components":
                    rows = connection.execute(
                        """
                        SELECT component_key, display_title, component_kind, display_order
                        FROM campaign_components
                        WHERE campaign_id = ?
                        ORDER BY display_order ASC, id ASC;
                        """,
                        (payload.campaign_id,),
                    ).fetchall()
                    components_list = [
                        {
                            "component_key": r["component_key"],
                            "display_title": r["display_title"],
                            "component_kind": r["component_kind"],
                            "display_order": r["display_order"],
                        }
                        for r in rows
                    ]
                    if components_list:
                        lines = [f"{i + 1}. {c['component_key']} — {c['display_title'] or '(no title)'}" for i, c in enumerate(components_list)]
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
                        component_row = connection.execute(
                            """
                            SELECT id FROM campaign_components
                            WHERE campaign_id = ? AND component_key = ?;
                            """,
                            (payload.campaign_id, active_component_ref),
                        ).fetchone()
                        if component_row is None:
                            result = {
                                "target": "clarify",
                                "message": f"Component '{active_component_ref}' not found in this campaign.",
                            }
                        else:
                            item_rows = connection.execute(
                                """
                                SELECT item_name, item_kind, item_value, duration_label, display_order
                                FROM campaign_component_items
                                WHERE component_id = ?
                                ORDER BY display_order ASC, id ASC;
                                """,
                                (component_row["id"],),
                            ).fetchall()
                            items_list = [
                                {
                                    "item_name": r["item_name"],
                                    "item_kind": r["item_kind"],
                                    "item_value": r["item_value"],
                                    "duration_label": r["duration_label"],
                                    "display_order": r["display_order"],
                                }
                                for r in item_rows
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

        config = resolve_config()
        llm_warning: str | None = None
        session_context = chat_store.get_context(session_id)

        if config.openrouter_api_key:
            # LLM path: translate natural language → structured command
            try:
                with connect_database(config) as connection:
                    result = translate_and_apply(
                        connection,
                        payload.campaign_id,
                        config.openrouter_api_key,
                        payload.message,
                    )
                    if result.get("target") != "clarify":
                        _persist_campaign_yaml_or_raise(connection, config, payload.campaign_id)
                    connection.commit()
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                _logger.warning("LLM call failed (%s); falling back to regex router", exc)
                llm_warning = "AI assistant unavailable; falling back to command syntax."
                with connect_database(config) as connection:
                    command = parse_chat_command(payload.message)
                    result = apply_chat_command(connection, payload.campaign_id, command, session_context=session_context)
                    if result.get("target") != "clarify":
                        _persist_campaign_yaml_or_raise(connection, config, payload.campaign_id)
                    connection.commit()
        else:
            # Regex-only path (no API key configured)
            with connect_database(config) as connection:
                command = parse_chat_command(payload.message)
                result = apply_chat_command(
                    connection, payload.campaign_id, command, session_context=session_context
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
                        _persist_campaign_yaml_or_raise(connection, config, payload.campaign_id)
                connection.commit()

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

    @app.post("/campaigns/{campaign_id}/save")
    def save_campaign(campaign_id: int, payload: CampaignSaveRequest | None = None) -> dict[str, Any]:
        request = payload or CampaignSaveRequest()
        config = resolve_config()

        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)

        if not config.commit_on_save:
            return {
                "campaign_id": campaign_id,
                "saved": False,
                "reason": "commit_on_save_disabled",
                "auto_commit": {"enabled": False, "performed": False, "commit_id": None},
            }

        if config.git_repo_path is None or not config.git_user_name or not config.git_user_email:
            return {
                "campaign_id": campaign_id,
                "saved": False,
                "reason": "git_config_incomplete",
                "auto_commit": {"enabled": True, "performed": False, "commit_id": None},
            }

        business_file: Path
        campaign_file: Path
        with connect_database(config) as connection:
            try:
                business_file, campaign_file = campaign_yaml_paths_for_id(connection, config.data_dir, campaign_id)
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
        repo_root = config.git_repo_path
        default_message = f"Save campaign {campaign_id} YAML"
        commit_message = (request.commit_message or default_message).strip()
        if commit_message == "":
            raise HTTPException(status_code=400, detail="commit_message cannot be empty")
        try:
            commit_id = auto_commit_paths(
                repo_root,
                [business_file, campaign_file],
                commit_message,
                user_name=config.git_user_name,
                user_email=config.git_user_email,
            )
        except GitStoreError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        auto_commit_performed = commit_id != ""

        return {
            "campaign_id": campaign_id,
            "saved": auto_commit_performed,
            "files": [str(business_file), str(campaign_file)],
            "auto_commit": {
                "enabled": True,
                "performed": auto_commit_performed,
                "commit_id": commit_id or None,
            },
        }

    @app.post("/campaigns/{campaign_id}/render", status_code=201)
    def render_artifact(
        campaign_id: int,
        payload: ArtifactRenderRequest | None = None,
    ) -> list[ArtifactResponse]:
        request = payload or ArtifactRenderRequest()
        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            try:
                results = render_campaign_artifact(
                    connection,
                    campaign_id,
                    config.output_dir,
                    artifact_type=request.artifact_type,
                    data_dir=config.data_dir,
                    images_per_page=config.images_per_page,
                    overwrite=request.overwrite,
                    custom_name=request.custom_name,
                )
                connection.commit()
            except ValueError as exc:
                raise HTTPException(status_code=409, detail={"reason": "file_exists", "message": str(exc)}) from exc
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        
        response_items = []
        for res in results:
            row = _get_artifact_row(config, res["id"])
            response_items.append(ArtifactResponse(**row))
        return response_items

    @app.get("/campaigns/{campaign_id}/artifacts")
    def list_artifacts(campaign_id: int) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_campaign(connection, campaign_id)
            rows = connection.execute(
                """
                SELECT id, campaign_id, artifact_type, file_path, checksum, status, created_at
                FROM generated_artifacts
                WHERE campaign_id = ?
                ORDER BY created_at DESC;
                """,
                (campaign_id,),
            ).fetchall()
        return {"items": [dict(r) for r in rows]}

    @app.get("/artifacts/{artifact_id}/download")
    def download_artifact(artifact_id: int):
        from fastapi.responses import FileResponse

        config = resolve_config()
        with connect_database(config) as connection:
            row = connection.execute(
                "SELECT id, file_path, artifact_type FROM generated_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        file_path = Path(row["file_path"])
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Artifact file missing")
        filename = file_path.name
        return FileResponse(
            path=str(file_path),
            media_type="application/pdf",
            filename=filename,
        )

    @app.get("/artifacts/{artifact_id}/view")
    def view_artifact(artifact_id: int):
        from fastapi.responses import FileResponse

        config = resolve_config()
        with connect_database(config) as connection:
            row = connection.execute(
                "SELECT id, file_path, artifact_type FROM generated_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Artifact not found")
        file_path = Path(row["file_path"])
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Artifact file missing")

        # Return inline PDF for iframe/browser preview.
        return FileResponse(path=str(file_path), media_type="application/pdf")

    @app.post("/data/sync")
    def sync_yaml_data() -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            summary = sync_data_directory(connection, config.data_dir)
            connection.commit()
        return {
            "businesses_synced": summary.businesses_synced,
            "campaigns_synced": summary.campaigns_synced,
            "data_dir": str(config.data_dir),
        }

    def _get_artifact_row(config, artifact_id: int) -> dict[str, Any]:
        with connect_database(config) as connection:
            row = connection.execute(
                "SELECT id, campaign_id, artifact_type, file_path, checksum, status, created_at "
                "FROM generated_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Artifact not found after insert")
        return dict(row)

    @app.get("/data-manager/businesses")
    def list_data_manager_businesses() -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            rows = connection.execute(
                """
                SELECT display_name, legal_name, timezone, is_active
                FROM businesses
                ORDER BY display_name ASC;
                """
            ).fetchall()

        return {
            "items": [
                {
                    "display_name": row["display_name"],
                    "legal_name": row["legal_name"],
                    "timezone": row["timezone"],
                    "is_active": bool(row["is_active"]),
                }
                for row in rows
            ]
        }

    @app.get("/data-manager/businesses/{business_name}")
    def get_data_manager_business(business_name: str) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            return _business_snapshot(connection, business_name)

    @app.get("/data-manager/businesses/{business_name}/campaigns")
    def list_data_manager_campaigns(business_name: str) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            business = connection.execute(
                "SELECT id FROM businesses WHERE display_name = ?;",
                (business_name,),
            ).fetchone()
            if business is None:
                raise HTTPException(status_code=404, detail="Business not found")

            rows = connection.execute(
                """
                SELECT campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date, details_json
                FROM campaigns
                WHERE business_id = ?
                ORDER BY campaign_name ASC, campaign_key ASC;
                """,
                (business["id"],),
            ).fetchall()

        return {
            "items": [
                {
                    "display_name": _campaign_display_name(row),
                    "campaign_name": row["campaign_name"],
                    "qualifier": row["campaign_key"] or None,
                    "title": row["title"],
                    "objective": row["objective"],
                    "footnote_text": row["footnote_text"],
                    "status": row["status"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                }
                for row in rows
            ]
        }

    @app.get("/data-manager/businesses/{business_name}/campaigns/{campaign_name}")
    def get_data_manager_campaign(
        business_name: str, campaign_name: str, qualifier: str | None = None
    ) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            return {
                "business": _business_snapshot(connection, business_name),
                "campaign": _campaign_snapshot(connection, business_name, campaign_name, qualifier),
            }

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend-static")

    return app


app = create_app()
