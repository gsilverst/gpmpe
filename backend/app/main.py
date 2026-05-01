from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
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
    require_component as _require_component,
    require_item as _require_item,
    require_template as _require_template,
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
    CampaignAsset,
    CampaignComponent,
    CampaignComponentItem,
    CampaignOffer,
    CampaignTemplateBinding,
    TemplateDefinition,
)
from .routes.artifacts import router as artifacts_router
from .routes.data_manager import router as data_manager_router
from .schemas import (
    BusinessCreate,
    BusinessResponse,
    BusinessUpdate,
    CampaignAssetCreate,
    CampaignCloneRequest,
    CampaignCreate,
    CampaignOfferCreate,
    CampaignTemplateBindingCreate,
    CampaignUpdate,
    ChatMessageRequest,
    ComponentCreate,
    ComponentItemCreate,
    ComponentItemUpdate,
    ComponentUpdate,
    StartupResolveRequest,
    TemplateDefinitionCreate,
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


ALLOWED_ASSET_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "application/pdf",
    "text/plain",
}


def _business_to_response(business: Business) -> BusinessResponse:
    from .models import BusinessContact, BusinessLocation

    # Get primary phone
    phone = next((c.contact_value for c in business.contacts if c.contact_type == 'phone' and c.is_primary), None)
    if phone is None:
        # Fallback to first phone contact if no primary set
        phone = next((c.contact_value for c in business.contacts if c.contact_type == 'phone'), None)

    # Get first location
    location = business.locations[0] if business.locations else None

    return BusinessResponse(
        id=business.id,
        legal_name=business.legal_name,
        display_name=business.display_name,
        timezone=business.timezone,
        is_active=business.is_active,
        phone=phone,
        address_line1=location.line1 if location else None,
        address_line2=location.line2 if location else None,
        city=location.city if location else None,
        state=location.state if location else None,
        postal_code=location.postal_code if location else None,
        country=location.country if location else None,
    )


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

    @app.post("/businesses", response_model=BusinessResponse, status_code=201)
    def create_business(payload: BusinessCreate, db: Session = Depends(get_db_session)) -> BusinessResponse:
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

        from .models import BusinessContact, BusinessLocation

        business = Business(
            legal_name=payload.legal_name.strip(),
            display_name=payload.display_name.strip(),
            timezone=payload.timezone.strip()
        )
        db.add(business)
        db.flush() # Get business.id

        if phone:
            contact = BusinessContact(
                business_id=business.id,
                contact_type="phone",
                contact_value=phone,
                is_primary=True
            )
            db.add(contact)

        if has_required_address:
            location = BusinessLocation(
                business_id=business.id,
                line1=address_line1,
                line2=address_line2 or None,
                city=city,
                state=state,
                postal_code=postal_code,
                country=country,
                hours_json='{}'
            )
            db.add(location)

        db.commit()
        db.refresh(business)
        return _business_to_response(business)

    @app.get("/businesses", response_model=list[BusinessResponse])
    def list_businesses(db: Session = Depends(get_db_session)) -> list[BusinessResponse]:
        businesses = db.query(Business).order_by(Business.id.asc()).all()
        return [_business_to_response(b) for b in businesses]

    @app.get("/businesses/{business_id}", response_model=BusinessResponse)
    def get_business(business_id: int, db: Session = Depends(get_db_session)) -> BusinessResponse:
        business = _require_business(db, business_id)
        return _business_to_response(business)

    @app.patch("/businesses/{business_id}", response_model=BusinessResponse)
    def update_business(business_id: int, payload: BusinessUpdate, db: Session = Depends(get_db_session)) -> BusinessResponse:
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

        business = _require_business(db, business_id)

        for field, value in updates.items():
            setattr(business, field, value)

        from .models import BusinessContact, BusinessLocation

        if phone_update is not None:
            # Simple approach: delete existing phone and add new one
            db.query(BusinessContact).filter(
                BusinessContact.business_id == business_id,
                BusinessContact.contact_type == 'phone'
            ).delete()
            if phone_update:
                contact = BusinessContact(
                    business_id=business_id,
                    contact_type="phone",
                    contact_value=phone_update,
                    is_primary=True
                )
                db.add(contact)

        if location_updates:
            # Get existing location or default values
            location = business.locations[0] if business.locations else None

            current_line1 = (location.line1 if location else "").strip()
            current_city = (location.city if location else "").strip()
            current_state = (location.state if location else "").strip()
            current_postal = (location.postal_code if location else "").strip()
            current_line2 = (location.line2 if location else "").strip()
            current_country = (location.country if location else "US").strip() or "US"

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

            # Re-create location
            db.query(BusinessLocation).filter(BusinessLocation.business_id == business_id).delete()
            if all(required):
                new_location = BusinessLocation(
                    business_id=business_id,
                    line1=next_line1,
                    line2=next_line2 or None,
                    city=next_city,
                    state=next_state,
                    postal_code=next_postal,
                    country=next_country,
                    hours_json='{}'
                )
                db.add(new_location)

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Business update conflicts with existing data") from exc

        config = resolve_config()
        for campaign in business.campaigns:
            persist_campaign_yaml_session_or_raise(db, config, campaign.id)

        db.refresh(business)
        return _business_to_response(business)

    @app.get("/businesses/{business_id}/campaigns/lookup")
    def lookup_campaigns_by_name(business_id: int, campaign_name: str, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        _require_business(db, business_id)

        campaigns = db.query(Campaign).filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == campaign_name.strip()
        ).order_by(Campaign.id.asc()).all()

        return {
            "campaign_name": campaign_name.strip(),
            "matches": [_campaign_row_to_dict(row.__dict__) for row in campaigns],
            "prompt": "open_existing_or_create_new" if campaigns else "create_new",
        }

    @app.post("/businesses/{business_id}/campaigns", status_code=201)
    def create_campaign(business_id: int, payload: CampaignCreate, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        normalized_name = payload.campaign_name.strip()
        normalized_key = (payload.campaign_key or "").strip()
        if normalized_key.lower() == "none":
            normalized_key = ""

        _require_business(db, business_id)

        # Check for name matches to suggest resolution
        name_matches = db.query(Campaign).filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == normalized_name
        ).order_by(Campaign.id.asc()).all()

        if name_matches and normalized_key == "":
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Campaign name already exists. Choose an existing campaign or provide campaign_key to create a new one.",
                    "resolution": "open_existing_or_create_new",
                    "matches": [_campaign_row_to_dict(row.__dict__) for row in name_matches],
                },
            )

        # Check for duplicate key
        duplicate = db.query(Campaign).filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == normalized_name,
            Campaign.campaign_key == normalized_key
        ).first()

        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Campaign with the same name and key already exists.",
                    "resolution": "open_existing",
                },
            )

        campaign = Campaign(
            business_id=business_id,
            campaign_name=normalized_name,
            campaign_key=normalized_key,
            title=payload.title.strip(),
            objective=payload.objective,
            footnote_text=payload.footnote_text,
            status=payload.status,
            start_date=payload.start_date,
            end_date=payload.end_date
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        config = resolve_config()
        persist_campaign_yaml_session_or_raise(db, config, campaign.id)

        return _campaign_row_to_dict(campaign.__dict__)

    @app.patch("/businesses/{business_id}/campaigns/{campaign_id}")
    def update_campaign(business_id: int, campaign_id: int, payload: CampaignUpdate, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No campaign fields provided")

        if "title" in updates and isinstance(updates["title"], str):
            updates["title"] = updates["title"].strip()
            if updates["title"] == "":
                raise HTTPException(status_code=400, detail="title cannot be empty")

        _require_business(db, business_id)
        campaign = db.query(Campaign).filter(
            Campaign.id == campaign_id,
            Campaign.business_id == business_id
        ).first()

        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")

        for field, value in updates.items():
            setattr(campaign, field, value)

        db.commit()
        db.refresh(campaign)

        config = resolve_config()
        persist_campaign_yaml_session_or_raise(db, config, campaign_id)

        return _campaign_row_to_dict(campaign.__dict__)

    @app.post("/businesses/{business_id}/campaigns/{campaign_id}/clone", status_code=201)
    def clone_campaign(business_id: int, campaign_id: int, payload: CampaignCloneRequest, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        new_name = payload.new_campaign_name.strip()
        new_key = (payload.campaign_key or "").strip()
        if new_name == "":
            raise HTTPException(status_code=400, detail="new_campaign_name cannot be empty")

        _require_business(db, business_id)
        source = db.query(Campaign).filter(
            Campaign.id == campaign_id,
            Campaign.business_id == business_id
        ).first()

        if source is None:
            raise HTTPException(status_code=404, detail="Campaign not found")

        name_matches = db.query(Campaign).filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == new_name
        ).all()

        if name_matches and new_key == "":
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Campaign name already exists. Provide campaign_key to make it unique.",
                    "resolution": "provide_secondary_key",
                    "matches": [
                        {"id": row.id, "campaign_key": row.campaign_key or None}
                        for row in name_matches
                    ],
                },
            )

        duplicate = db.query(Campaign).filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == new_name,
            Campaign.campaign_key == new_key
        ).first()

        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Campaign name and secondary key already exist")

        destination_slug = new_name if new_key == "" else f"{new_name}-{new_key}"

        config = resolve_config()
        try:
            record = clone_campaign_directory_session(
                db,
                config.data_dir,
                source_campaign_name=source.campaign_name,
                source_campaign_key=source.campaign_key or "",
                new_campaign_name=new_name,
                new_campaign_key=new_key or None,
                destination_directory_name=destination_slug,
                business_name=source.business.display_name,
            )
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        new_campaign = db.query(Campaign).filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == record.payload.get("campaign_name"),
            Campaign.campaign_key == (record.payload.get("qualifier") or "")
        ).order_by(Campaign.id.desc()).first()

        if new_campaign is None:
            raise HTTPException(status_code=500, detail="Campaign clone failed")

        return _campaign_row_to_dict(new_campaign.__dict__)

    @app.get("/businesses/{business_id}/campaigns")
    def list_campaigns(business_id: int, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        _require_business(db, business_id)
        campaigns = db.query(Campaign).filter(
            Campaign.business_id == business_id
        ).order_by(Campaign.campaign_name.asc(), Campaign.campaign_key.asc(), Campaign.id.asc()).all()

        return {"items": [_campaign_row_to_dict(row.__dict__) for row in campaigns]}

    @app.get("/businesses/{business_id}/campaigns/{campaign_id}")
    def get_campaign(business_id: int, campaign_id: int, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        _require_business(db, business_id)
        campaign = db.query(Campaign).filter(
            Campaign.id == campaign_id,
            Campaign.business_id == business_id
        ).first()

        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        return _campaign_row_to_dict(campaign.__dict__)


    @app.post("/campaigns/{campaign_id}/offers", status_code=201)
    def create_campaign_offer(campaign_id: int, payload: CampaignOfferCreate, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        new_start = _parse_iso_date(payload.start_date, "start_date")
        new_end = _parse_iso_date(payload.end_date, "end_date")
        if (new_start is None) != (new_end is None):
            raise HTTPException(status_code=400, detail="Offer requires both start_date and end_date when scheduling")
        if new_start is not None and new_end is not None and new_start > new_end:
            raise HTTPException(status_code=400, detail="Offer start_date cannot be after end_date")

        campaign = _require_campaign(db, campaign_id)

        # Check for overlaps
        for offer in campaign.offers:
            existing_start = _parse_iso_date(offer.start_date, "start_date")
            existing_end = _parse_iso_date(offer.end_date, "end_date")
            if _offers_overlap(new_start, new_end, existing_start, existing_end):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Offer date window overlaps with an existing offer",
                        "existing_offer_id": offer.id,
                    },
                )

        new_offer = CampaignOffer(
            campaign_id=campaign_id,
            offer_name=payload.offer_name.strip(),
            offer_type=payload.offer_type.strip(),
            offer_value=payload.offer_value,
            start_date=payload.start_date,
            end_date=payload.end_date,
            terms_text=payload.terms_text
        )
        db.add(new_offer)
        db.commit()
        db.refresh(new_offer)

        config = resolve_config()
        persist_campaign_yaml_session_or_raise(db, config, campaign_id)

        return {
            "id": new_offer.id,
            "campaign_id": new_offer.campaign_id,
            "offer_name": new_offer.offer_name,
            "offer_type": new_offer.offer_type,
            "offer_value": new_offer.offer_value,
            "start_date": new_offer.start_date,
            "end_date": new_offer.end_date,
            "terms_text": new_offer.terms_text,
        }

    @app.get("/campaigns/{campaign_id}/offers")
    def list_campaign_offers(campaign_id: int, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        campaign = _require_campaign(db, campaign_id)
        # Sort manually or via query. Manual sort for simple relationship access.
        sorted_offers = sorted(campaign.offers, key=lambda o: (o.start_date or "", o.id))

        return {
            "items": [
                {
                    "id": row.id,
                    "campaign_id": row.campaign_id,
                    "offer_name": row.offer_name,
                    "offer_type": row.offer_type,
                    "offer_value": row.offer_value,
                    "start_date": row.start_date,
                    "end_date": row.end_date,
                    "terms_text": row.terms_text,
                }
                for row in sorted_offers
            ]
        }

    @app.post("/campaigns/{campaign_id}/assets", status_code=201)
    def create_campaign_asset(campaign_id: int, payload: CampaignAssetCreate, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        mime_type = payload.mime_type.strip().lower()
        if mime_type not in ALLOWED_ASSET_MIME_TYPES:
            raise HTTPException(status_code=400, detail="Unsupported mime_type")

        _require_campaign(db, campaign_id)

        asset = CampaignAsset(
            campaign_id=campaign_id,
            asset_type=payload.asset_type.strip(),
            source_type=payload.source_type,
            mime_type=mime_type,
            source_path=payload.source_path.strip(),
            width=payload.width,
            height=payload.height,
            metadata_json=json.dumps(payload.metadata or {})
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

        config = resolve_config()
        persist_campaign_yaml_session_or_raise(db, config, campaign_id)

        return {
            "id": asset.id,
            "campaign_id": asset.campaign_id,
            "asset_type": asset.asset_type,
            "source_type": asset.source_type,
            "mime_type": asset.mime_type,
            "source_path": asset.source_path,
            "width": asset.width,
            "height": asset.height,
            "metadata": json.loads(asset.metadata_json or "{}"),
        }

    @app.get("/campaigns/{campaign_id}/assets")
    def list_campaign_assets(campaign_id: int, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        campaign = _require_campaign(db, campaign_id)
        return {
            "items": [
                {
                    "id": row.id,
                    "campaign_id": row.campaign_id,
                    "asset_type": row.asset_type,
                    "source_type": row.source_type,
                    "mime_type": row.mime_type,
                    "source_path": row.source_path,
                    "width": row.width,
                    "height": row.height,
                    "metadata": json.loads(row.metadata_json or "{}"),
                }
                for row in campaign.assets
            ]
        }

    @app.post("/templates", status_code=201)
    def create_template(payload: TemplateDefinitionCreate, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        duplicate = db.query(TemplateDefinition).filter(
            TemplateDefinition.template_name == payload.template_name.strip()
        ).first()

        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Template name already exists")

        template = TemplateDefinition(
            template_name=payload.template_name.strip(),
            template_kind=payload.template_kind.strip(),
            size_spec=payload.size_spec,
            layout_json=json.dumps(payload.layout or {}),
            default_values_json=json.dumps(payload.default_values or {})
        )
        db.add(template)
        db.commit()
        db.refresh(template)

        return {
            "id": template.id,
            "template_name": template.template_name,
            "template_kind": template.template_kind,
            "size_spec": template.size_spec,
            "layout": json.loads(template.layout_json or "{}"),
            "default_values": json.loads(template.default_values_json or "{}"),
        }

    @app.get("/templates")
    def list_templates(db: Session = Depends(get_db_session)) -> dict[str, Any]:
        rows = db.query(TemplateDefinition).order_by(TemplateDefinition.template_name.asc()).all()
        return {
            "items": [
                {
                    "id": row.id,
                    "template_name": row.template_name,
                    "template_kind": row.template_kind,
                    "size_spec": row.size_spec,
                    "layout": json.loads(row.layout_json or "{}"),
                    "default_values": json.loads(row.default_values_json or "{}"),
                }
                for row in rows
            ]
        }

    @app.post("/campaigns/{campaign_id}/template-bindings", status_code=201)
    def create_template_binding(campaign_id: int, payload: CampaignTemplateBindingCreate, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        campaign = _require_campaign(db, campaign_id)

        template = db.get(TemplateDefinition, payload.template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Template not found")

        # Deactivate existing bindings
        db.query(CampaignTemplateBinding).filter(
            CampaignTemplateBinding.campaign_id == campaign_id
        ).update({"is_active": False})

        binding = CampaignTemplateBinding(
            campaign_id=campaign_id,
            template_id=payload.template_id,
            override_values_json=json.dumps(payload.override_values or {}),
            is_active=True
        )
        db.add(binding)
        db.commit()
        db.refresh(binding)

        config = resolve_config()
        persist_campaign_yaml_session_or_raise(db, config, campaign_id)

        defaults = json.loads(template.default_values_json or "{}")
        overrides = payload.override_values or {}
        effective_values = {**defaults, **overrides}

        return {
            "id": binding.id,
            "campaign_id": binding.campaign_id,
            "template_id": binding.template_id,
            "template_name": template.template_name,
            "template_kind": template.template_kind,
            "size_spec": template.size_spec,
            "layout": json.loads(template.layout_json or "{}"),
            "default_values": defaults,
            "override_values": overrides,
            "effective_values": effective_values,
            "is_active": binding.is_active,
        }

    @app.get("/campaigns/{campaign_id}/template-binding/effective")
    def get_effective_template_binding(campaign_id: int, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        campaign = _require_campaign(db, campaign_id)

        binding = db.query(CampaignTemplateBinding).filter(
            CampaignTemplateBinding.campaign_id == campaign_id,
            CampaignTemplateBinding.is_active == True
        ).order_by(CampaignTemplateBinding.id.desc()).first()

        if binding is None:
            raise HTTPException(status_code=404, detail="No active template binding for campaign")

        template = binding.template
        defaults = json.loads(template.default_values_json or "{}")
        overrides = json.loads(binding.override_values_json or "{}")
        effective_values = {**defaults, **overrides}

        return {
            "id": binding.id,
            "campaign_id": binding.campaign_id,
            "template_id": binding.template_id,
            "template_name": template.template_name,
            "template_kind": template.template_kind,
            "size_spec": template.size_spec,
            "layout": json.loads(template.layout_json or "{}"),
            "default_values": defaults,
            "override_values": overrides,
            "effective_values": effective_values,
            "is_active": binding.is_active,
        }

    @app.get("/campaigns/{campaign_id}/components")
    def list_campaign_components(campaign_id: int, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        campaign = _require_campaign(db, campaign_id)

        # Sort components
        sorted_components = sorted(campaign.components, key=lambda c: (c.display_order, c.id))

        items_tree = []
        for c in sorted_components:
            # Sort items
            sorted_items = sorted(c.items, key=lambda i: (i.display_order, i.id))
            items_tree.append({
                "id": c.id,
                "component_key": c.component_key,
                "component_kind": c.component_kind,
                "render_region": c.render_region,
                "render_mode": c.render_mode,
                "style": json.loads(c.style_json or "{}"),
                "display_title": c.display_title,
                "subtitle": c.subtitle,
                "description_text": c.description_text,
                "footnote_text": c.footnote_text,
                "background_color": c.background_color,
                "header_accent_color": c.header_accent_color,
                "display_order": c.display_order,
                "items": [
                    {
                        "id": ir.id,
                        "item_name": ir.item_name,
                        "item_kind": ir.item_kind,
                        "duration_label": ir.duration_label,
                        "item_value": ir.item_value,
                        "background_color": ir.background_color,
                        "render_role": ir.render_role,
                        "style": json.loads(ir.style_json or "{}"),
                        "description_text": ir.description_text,
                        "terms_text": ir.terms_text,
                        "display_order": ir.display_order,
                    }
                    for ir in sorted_items
                ]
            })

        return {
            "campaign_id": campaign_id,
            "items": items_tree,
        }

    @app.post("/campaigns/{campaign_id}/components", status_code=201)
    def create_component(campaign_id: int, payload: ComponentCreate, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        _require_campaign(db, campaign_id)

        # Check for duplicate key
        duplicate = db.query(CampaignComponent).filter(
            CampaignComponent.campaign_id == campaign_id,
            CampaignComponent.component_key == payload.component_key.strip()
        ).first()

        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Component key already exists in this campaign")

        component = CampaignComponent(
            campaign_id=campaign_id,
            component_key=payload.component_key.strip(),
            component_kind=payload.component_kind.strip(),
            render_region=payload.render_region,
            render_mode=payload.render_mode,
            style_json=json.dumps(payload.style or {}),
            display_title=payload.display_title.strip(),
            background_color=payload.background_color,
            header_accent_color=payload.header_accent_color,
            footnote_text=payload.footnote_text,
            subtitle=payload.subtitle,
            description_text=payload.description_text,
            display_order=payload.display_order
        )
        db.add(component)
        db.commit()
        db.refresh(component)

        config = resolve_config()
        persist_campaign_yaml_session_or_raise(db, config, campaign_id)

        return {"id": component.id, "campaign_id": campaign_id, **payload.model_dump()}

    @app.patch("/campaigns/{campaign_id}/components/{component_id}")
    def update_component(campaign_id: int, component_id: int, payload: ComponentUpdate, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No component fields provided")

        _require_campaign(db, campaign_id)
        component = db.query(CampaignComponent).filter(
            CampaignComponent.id == component_id,
            CampaignComponent.campaign_id == campaign_id
        ).first()

        if component is None:
            raise HTTPException(status_code=404, detail="Component not found")

        if "style" in updates:
            updates["style_json"] = json.dumps(updates.pop("style"))

        for field, value in updates.items():
            setattr(component, field, value)

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="Component update conflicts with existing data") from exc

        config = resolve_config()
        persist_campaign_yaml_session_or_raise(db, config, campaign_id)

        db.refresh(component)
        return {"id": component.id, "campaign_id": campaign_id, "updates": list(updates.keys())}

    @app.delete("/campaigns/{campaign_id}/components/{component_id}", status_code=204)
    def delete_component(campaign_id: int, component_id: int, db: Session = Depends(get_db_session)) -> None:
        _require_campaign(db, campaign_id)
        component = db.query(CampaignComponent).filter(
            CampaignComponent.id == component_id,
            CampaignComponent.campaign_id == campaign_id
        ).first()

        if component is None:
            raise HTTPException(status_code=404, detail="Component not found")

        db.delete(component)
        db.commit()

        config = resolve_config()
        persist_campaign_yaml_session_or_raise(db, config, campaign_id)

    @app.post("/campaigns/{campaign_id}/components/{component_id}/items", status_code=201)
    def create_component_item(campaign_id: int, component_id: int, payload: ComponentItemCreate, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        _require_campaign(db, campaign_id)
        # Component must belong to this campaign
        component = db.query(CampaignComponent).filter(
            CampaignComponent.id == component_id,
            CampaignComponent.campaign_id == campaign_id
        ).first()
        if component is None:
            raise HTTPException(status_code=404, detail="Component not found")

        item = CampaignComponentItem(
            component_id=component_id,
            item_name=payload.item_name.strip(),
            item_kind=payload.item_kind.strip(),
            render_role=payload.render_role,
            style_json=json.dumps(payload.style or {}),
            duration_label=payload.duration_label,
            item_value=payload.item_value,
            background_color=payload.background_color,
            description_text=payload.description_text,
            terms_text=payload.terms_text,
            display_order=payload.display_order
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        config = resolve_config()
        persist_campaign_yaml_session_or_raise(db, config, campaign_id)

        return {"id": item.id, "component_id": component_id, **payload.model_dump()}

    @app.patch("/campaigns/{campaign_id}/components/{component_id}/items/{item_id}")
    def update_component_item(campaign_id: int, component_id: int, item_id: int, payload: ComponentItemUpdate, db: Session = Depends(get_db_session)) -> dict[str, Any]:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No item fields provided")

        _require_campaign(db, campaign_id)
        item = db.query(CampaignComponentItem).join(CampaignComponent).filter(
            CampaignComponentItem.id == item_id,
            CampaignComponentItem.component_id == component_id,
            CampaignComponent.campaign_id == campaign_id
        ).first()

        if item is None:
            raise HTTPException(status_code=404, detail="Component item not found")

        if "style" in updates:
            updates["style_json"] = json.dumps(updates.pop("style"))

        for field, value in updates.items():
            setattr(item, field, value)

        db.commit()
        db.refresh(item)

        config = resolve_config()
        persist_campaign_yaml_session_or_raise(db, config, campaign_id)

        return {"id": item.id, "component_id": component_id, "updates": list(updates.keys())}

    @app.delete("/campaigns/{campaign_id}/components/{component_id}/items/{item_id}", status_code=204)
    def delete_component_item(campaign_id: int, component_id: int, item_id: int, db: Session = Depends(get_db_session)) -> None:
        _require_campaign(db, campaign_id)
        item = db.query(CampaignComponentItem).join(CampaignComponent).filter(
            CampaignComponentItem.id == item_id,
            CampaignComponentItem.component_id == component_id,
            CampaignComponent.campaign_id == campaign_id
        ).first()

        if item is None:
            raise HTTPException(status_code=404, detail="Component item not found")

        db.delete(item)
        db.commit()

        config = resolve_config()
        persist_campaign_yaml_session_or_raise(db, config, campaign_id)

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
    app.include_router(data_manager_router)

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend-static")

    return app


app = create_app()
