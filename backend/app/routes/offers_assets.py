from __future__ import annotations

from datetime import date
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import resolve_config
from ..dependencies import get_db_session, require_campaign
from ..models import CampaignAsset, CampaignOffer
from ..schemas import CampaignAssetCreate, CampaignOfferCreate
from ..services.yaml_persistence import persist_campaign_yaml_session_or_raise

router = APIRouter(prefix="/campaigns/{campaign_id}")

ALLOWED_ASSET_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "application/pdf",
    "text/plain",
}


def _parse_iso_date(value: str | None, field_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}; expected YYYY-MM-DD") from exc


def _offers_overlap(
    start_a: date | None,
    end_a: date | None,
    start_b: date | None,
    end_b: date | None,
) -> bool:
    if start_a is None or end_a is None or start_b is None or end_b is None:
        return False
    return start_a <= end_b and start_b <= end_a


@router.post("/offers", status_code=201)
def create_campaign_offer(
    campaign_id: int,
    payload: CampaignOfferCreate,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    new_start = _parse_iso_date(payload.start_date, "start_date")
    new_end = _parse_iso_date(payload.end_date, "end_date")
    if (new_start is None) != (new_end is None):
        raise HTTPException(status_code=400, detail="Offer requires both start_date and end_date when scheduling")
    if new_start is not None and new_end is not None and new_start > new_end:
        raise HTTPException(status_code=400, detail="Offer start_date cannot be after end_date")

    campaign = require_campaign(db, campaign_id)

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
        terms_text=payload.terms_text,
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


@router.get("/offers")
def list_campaign_offers(campaign_id: int, db: Session = Depends(get_db_session)) -> dict[str, Any]:
    campaign = require_campaign(db, campaign_id)
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


@router.post("/assets", status_code=201)
def create_campaign_asset(
    campaign_id: int,
    payload: CampaignAssetCreate,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    mime_type = payload.mime_type.strip().lower()
    if mime_type not in ALLOWED_ASSET_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported mime_type")

    require_campaign(db, campaign_id)

    asset = CampaignAsset(
        campaign_id=campaign_id,
        asset_type=payload.asset_type.strip(),
        source_type=payload.source_type,
        mime_type=mime_type,
        source_path=payload.source_path.strip(),
        width=payload.width,
        height=payload.height,
        metadata_json=json.dumps(payload.metadata or {}),
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


@router.get("/assets")
def list_campaign_assets(campaign_id: int, db: Session = Depends(get_db_session)) -> dict[str, Any]:
    campaign = require_campaign(db, campaign_id)
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
