from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import resolve_config
from ..data_sync import clone_campaign_directory_session
from ..dependencies import (
    get_db_session,
    require_business,
)
from ..models import (
    Business,
    BusinessContact,
    BusinessLocation,
    Campaign,
)
from ..schemas import (
    BusinessCreate,
    BusinessResponse,
    BusinessUpdate,
    CampaignCloneRequest,
    CampaignCreate,
    CampaignUpdate,
)
from ..services.yaml_persistence import persist_campaign_yaml_session_or_raise

router = APIRouter()


def _business_to_response(business: Business) -> BusinessResponse:
    phone = next(
        (c.contact_value for c in business.contacts if c.contact_type == "phone" and c.is_primary),
        None,
    )
    if phone is None:
        phone = next((c.contact_value for c in business.contacts if c.contact_type == "phone"), None)

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


@router.post("/businesses", response_model=BusinessResponse, status_code=201)
def create_business(
    payload: BusinessCreate,
    db: Session = Depends(get_db_session),
) -> BusinessResponse:
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

    business = Business(
        legal_name=payload.legal_name.strip(),
        display_name=payload.display_name.strip(),
        timezone=payload.timezone.strip(),
    )
    db.add(business)
    db.flush()

    if phone:
        contact = BusinessContact(
            business_id=business.id,
            contact_type="phone",
            contact_value=phone,
            is_primary=True,
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
            hours_json="{}",
        )
        db.add(location)

    db.commit()
    db.refresh(business)
    return _business_to_response(business)


@router.get("/businesses", response_model=list[BusinessResponse])
def list_businesses(db: Session = Depends(get_db_session)) -> list[BusinessResponse]:
    businesses = db.query(Business).order_by(Business.id.asc()).all()
    return [_business_to_response(b) for b in businesses]


@router.get("/businesses/{business_id}", response_model=BusinessResponse)
def get_business(
    business_id: int,
    db: Session = Depends(get_db_session),
) -> BusinessResponse:
    business = require_business(db, business_id)
    return _business_to_response(business)


@router.patch("/businesses/{business_id}", response_model=BusinessResponse)
def update_business(
    business_id: int,
    payload: BusinessUpdate,
    db: Session = Depends(get_db_session),
) -> BusinessResponse:
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

    business = require_business(db, business_id)

    for field, value in updates.items():
        setattr(business, field, value)

    if phone_update is not None:
        db.query(BusinessContact).filter(
            BusinessContact.business_id == business_id,
            BusinessContact.contact_type == "phone",
        ).delete()
        if phone_update:
            contact = BusinessContact(
                business_id=business_id,
                contact_type="phone",
                contact_value=phone_update,
                is_primary=True,
            )
            db.add(contact)

    if location_updates:
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
                hours_json="{}",
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


@router.get("/businesses/{business_id}/campaigns/lookup")
def lookup_campaigns_by_name(
    business_id: int,
    campaign_name: str,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    require_business(db, business_id)

    campaigns = (
        db.query(Campaign)
        .filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == campaign_name.strip(),
        )
        .order_by(Campaign.id.asc())
        .all()
    )

    return {
        "campaign_name": campaign_name.strip(),
        "matches": [_campaign_row_to_dict(row.__dict__) for row in campaigns],
        "prompt": "open_existing_or_create_new" if campaigns else "create_new",
    }


@router.post("/businesses/{business_id}/campaigns", status_code=201)
def create_campaign(
    business_id: int,
    payload: CampaignCreate,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    normalized_name = payload.campaign_name.strip()
    normalized_key = (payload.campaign_key or "").strip()
    if normalized_key.lower() == "none":
        normalized_key = ""

    require_business(db, business_id)

    name_matches = (
        db.query(Campaign)
        .filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == normalized_name,
        )
        .order_by(Campaign.id.asc())
        .all()
    )

    if name_matches and normalized_key == "":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Campaign name already exists. Choose an existing campaign or provide campaign_key to create a new one.",
                "resolution": "open_existing_or_create_new",
                "matches": [_campaign_row_to_dict(row.__dict__) for row in name_matches],
            },
        )

    duplicate = (
        db.query(Campaign)
        .filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == normalized_name,
            Campaign.campaign_key == normalized_key,
        )
        .first()
    )

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
        end_date=payload.end_date,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    config = resolve_config()
    persist_campaign_yaml_session_or_raise(db, config, campaign.id)

    return _campaign_row_to_dict(campaign.__dict__)


@router.patch("/businesses/{business_id}/campaigns/{campaign_id}")
def update_campaign(
    business_id: int,
    campaign_id: int,
    payload: CampaignUpdate,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No campaign fields provided")

    if "title" in updates and isinstance(updates["title"], str):
        updates["title"] = updates["title"].strip()
        if updates["title"] == "":
            raise HTTPException(status_code=400, detail="title cannot be empty")

    require_business(db, business_id)
    campaign = (
        db.query(Campaign)
        .filter(
            Campaign.id == campaign_id,
            Campaign.business_id == business_id,
        )
        .first()
    )

    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    for field, value in updates.items():
        setattr(campaign, field, value)

    db.commit()
    db.refresh(campaign)

    config = resolve_config()
    persist_campaign_yaml_session_or_raise(db, config, campaign_id)

    return _campaign_row_to_dict(campaign.__dict__)


@router.post("/businesses/{business_id}/campaigns/{campaign_id}/clone", status_code=201)
def clone_campaign(
    business_id: int,
    campaign_id: int,
    payload: CampaignCloneRequest,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    new_name = payload.new_campaign_name.strip()
    new_key = (payload.campaign_key or "").strip()
    if new_name == "":
        raise HTTPException(status_code=400, detail="new_campaign_name cannot be empty")

    require_business(db, business_id)
    source = (
        db.query(Campaign)
        .filter(
            Campaign.id == campaign_id,
            Campaign.business_id == business_id,
        )
        .first()
    )

    if source is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    name_matches = (
        db.query(Campaign)
        .filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == new_name,
        )
        .all()
    )

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

    duplicate = (
        db.query(Campaign)
        .filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == new_name,
            Campaign.campaign_key == new_key,
        )
        .first()
    )

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

    new_campaign = (
        db.query(Campaign)
        .filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == record.payload.get("campaign_name"),
            Campaign.campaign_key == (record.payload.get("qualifier") or ""),
        )
        .order_by(Campaign.id.desc())
        .first()
    )

    if new_campaign is None:
        raise HTTPException(status_code=500, detail="Campaign clone failed")

    return _campaign_row_to_dict(new_campaign.__dict__)


@router.get("/businesses/{business_id}/campaigns")
def list_campaigns(
    business_id: int,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    require_business(db, business_id)
    campaigns = (
        db.query(Campaign)
        .filter(Campaign.business_id == business_id)
        .order_by(Campaign.campaign_name.asc(), Campaign.campaign_key.asc(), Campaign.id.asc())
        .all()
    )

    return {"items": [_campaign_row_to_dict(row.__dict__) for row in campaigns]}


@router.get("/businesses/{business_id}/campaigns/{campaign_id}")
def get_campaign(
    business_id: int,
    campaign_id: int,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    require_business(db, business_id)
    campaign = (
        db.query(Campaign)
        .filter(
            Campaign.id == campaign_id,
            Campaign.business_id == business_id,
        )
        .first()
    )

    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _campaign_row_to_dict(campaign.__dict__)
