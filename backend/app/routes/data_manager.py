from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..dependencies import get_db_session
from ..services.data_manager import (
    business_snapshot,
    campaign_snapshot,
    list_business_summaries,
    list_campaign_summaries,
)

router = APIRouter(prefix="/data-manager")


@router.get("/businesses")
def list_data_manager_businesses(db: Session = Depends(get_db_session)) -> dict[str, Any]:
    return {"items": list_business_summaries(db)}


@router.get("/businesses/{business_name}")
def get_data_manager_business(
    business_name: str,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return business_snapshot(db, business_name)


@router.get("/businesses/{business_name}/campaigns")
def list_data_manager_campaigns(
    business_name: str,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return {"items": list_campaign_summaries(db, business_name)}


@router.get("/businesses/{business_name}/campaigns/{campaign_name}")
def get_data_manager_campaign(
    business_name: str,
    campaign_name: str,
    qualifier: str | None = None,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return {
        "business": business_snapshot(db, business_name),
        "campaign": campaign_snapshot(db, business_name, campaign_name, qualifier),
    }
