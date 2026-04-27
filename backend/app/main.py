from __future__ import annotations

from contextlib import asynccontextmanager
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


def _require_business(connection: Any, business_id: int) -> None:
    row = connection.execute("SELECT id FROM businesses WHERE id = ?;", (business_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Business not found")


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

    return app


app = create_app()
