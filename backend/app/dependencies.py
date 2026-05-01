from __future__ import annotations

from collections.abc import Iterator

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import resolve_config
from .db import get_engine, get_session_factory, initialize_database
from .models import (
    Business,
    Campaign,
    CampaignComponent,
    CampaignComponentItem,
    TemplateDefinition,
)


def get_db_session() -> Iterator[Session]:
    config = resolve_config()
    initialize_database(config)
    engine = get_engine(config)
    session_factory = get_session_factory(engine)
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def require_business(db: Session, business_id: int) -> Business:
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


def require_campaign(db: Session, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def require_template(db: Session, template_id: int) -> TemplateDefinition:
    template = db.get(TemplateDefinition, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


def require_component(db: Session, component_id: int) -> CampaignComponent:
    component = db.get(CampaignComponent, component_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")
    return component


def require_item(db: Session, item_id: int) -> CampaignComponentItem:
    item = db.get(CampaignComponentItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Component item not found")
    return item
