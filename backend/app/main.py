from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
import json
from typing import Literal
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import resolve_config
from .db import connect_database, initialize_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    config = resolve_config()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    initialize_database(config)
    yield


class BusinessCreate(BaseModel):
    legal_name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    timezone: str = Field(default="America/New_York", min_length=1)


class BusinessResponse(BaseModel):
    id: int
    legal_name: str
    display_name: str
    timezone: str
    is_active: bool


class CampaignCreate(BaseModel):
    campaign_name: str = Field(min_length=1)
    campaign_key: str | None = None
    title: str = Field(min_length=1)
    objective: str | None = None
    status: Literal["draft", "active", "paused", "completed", "archived"] = "draft"
    start_date: str | None = None
    end_date: str | None = None


class CampaignUpdate(BaseModel):
    title: str | None = None
    objective: str | None = None
    status: Literal["draft", "active", "paused", "completed", "archived"] | None = None
    start_date: str | None = None
    end_date: str | None = None


class CampaignOfferCreate(BaseModel):
    offer_name: str = Field(min_length=1)
    offer_type: str = Field(default="discount", min_length=1)
    offer_value: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    terms_text: str | None = None


class CampaignAssetCreate(BaseModel):
    asset_type: str = Field(min_length=1)
    source_type: Literal["upload", "url", "generated"]
    mime_type: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] | None = None


class TemplateDefinitionCreate(BaseModel):
    template_name: str = Field(min_length=1)
    template_kind: str = Field(min_length=1)
    size_spec: str | None = None
    layout: dict[str, Any] | None = None
    default_values: dict[str, Any] | None = None


class CampaignTemplateBindingCreate(BaseModel):
    template_id: int
    override_values: dict[str, Any] | None = None


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
        "status": row["status"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
    }


def create_app() -> FastAPI:
    app = FastAPI(title="GPMPG API", version="0.1.0", lifespan=lifespan)

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

    @app.post("/businesses", response_model=BusinessResponse, status_code=201)
    def create_business(payload: BusinessCreate) -> BusinessResponse:
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
            row = connection.execute(
                """
                SELECT id, legal_name, display_name, timezone, is_active
                FROM businesses
                WHERE id = ?;
                """,
                (business_id,),
            ).fetchone()
            connection.commit()

        if row is None:
            raise HTTPException(status_code=500, detail="Business creation failed")

        return BusinessResponse(
            id=row["id"],
            legal_name=row["legal_name"],
            display_name=row["display_name"],
            timezone=row["timezone"],
            is_active=bool(row["is_active"]),
        )

    @app.get("/businesses", response_model=list[BusinessResponse])
    def list_businesses() -> list[BusinessResponse]:
        config = resolve_config()
        with connect_database(config) as connection:
            rows = connection.execute(
                """
                SELECT id, legal_name, display_name, timezone, is_active
                FROM businesses
                ORDER BY id ASC;
                """
            ).fetchall()

        return [
            BusinessResponse(
                id=row["id"],
                legal_name=row["legal_name"],
                display_name=row["display_name"],
                timezone=row["timezone"],
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    @app.get("/businesses/{business_id}/campaigns/lookup")
    def lookup_campaigns_by_name(business_id: int, campaign_name: str) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_business(connection, business_id)
            rows = connection.execute(
                """
                SELECT id, business_id, campaign_name, campaign_key, title, objective, status, start_date, end_date
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
                SELECT id, business_id, campaign_name, campaign_key, title, objective, status, start_date, end_date
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
                  business_id, campaign_name, campaign_key, title, objective, status, start_date, end_date
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    business_id,
                    normalized_name,
                    normalized_key,
                    payload.title.strip(),
                    payload.objective,
                    payload.status,
                    payload.start_date,
                    payload.end_date,
                ),
            )
            campaign_id = int(cursor.lastrowid)
            row = connection.execute(
                """
                SELECT id, business_id, campaign_name, campaign_key, title, objective, status, start_date, end_date
                FROM campaigns
                WHERE id = ?;
                """,
                (campaign_id,),
            ).fetchone()
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
                SELECT id, business_id, campaign_name, campaign_key, title, objective, status, start_date, end_date
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
                SELECT id, business_id, campaign_name, campaign_key, title, objective, status, start_date, end_date
                FROM campaigns
                WHERE id = ?;
                """,
                (campaign_id,),
            ).fetchone()
            connection.commit()

        if updated is None:
            raise HTTPException(status_code=500, detail="Campaign update failed")
        return _campaign_row_to_dict(updated)

    @app.get("/businesses/{business_id}/campaigns")
    def list_campaigns(business_id: int) -> dict[str, Any]:
        config = resolve_config()
        with connect_database(config) as connection:
            _require_business(connection, business_id)
            rows = connection.execute(
                """
                SELECT id, business_id, campaign_name, campaign_key, title, objective, status, start_date, end_date
                FROM campaigns
                WHERE business_id = ?
                ORDER BY campaign_name ASC, campaign_key ASC, id ASC;
                """,
                (business_id,),
            ).fetchall()

        return {"items": [_campaign_row_to_dict(row) for row in rows]}

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

    return app


app = create_app()
