from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import resolve_config
from ..dependencies import get_db_session, require_campaign
from ..models import CampaignComponent, CampaignComponentItem
from ..schemas import ComponentCreate, ComponentItemCreate, ComponentItemUpdate, ComponentUpdate
from ..services.yaml_persistence import persist_campaign_yaml_session_or_raise

router = APIRouter(prefix="/campaigns/{campaign_id}/components")


@router.get("")
def list_campaign_components(
    campaign_id: int,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    campaign = require_campaign(db, campaign_id)
    sorted_components = sorted(campaign.components, key=lambda c: (c.display_order, c.id))

    items_tree = []
    for component in sorted_components:
        sorted_items = sorted(component.items, key=lambda i: (i.display_order, i.id))
        items_tree.append(
            {
                "id": component.id,
                "component_key": component.component_key,
                "component_kind": component.component_kind,
                "render_region": component.render_region,
                "render_mode": component.render_mode,
                "style": json.loads(component.style_json or "{}"),
                "display_title": component.display_title,
                "subtitle": component.subtitle,
                "description_text": component.description_text,
                "footnote_text": component.footnote_text,
                "background_color": component.background_color,
                "header_accent_color": component.header_accent_color,
                "display_order": component.display_order,
                "items": [
                    {
                        "id": item.id,
                        "item_name": item.item_name,
                        "item_kind": item.item_kind,
                        "duration_label": item.duration_label,
                        "item_value": item.item_value,
                        "background_color": item.background_color,
                        "render_role": item.render_role,
                        "style": json.loads(item.style_json or "{}"),
                        "description_text": item.description_text,
                        "terms_text": item.terms_text,
                        "display_order": item.display_order,
                    }
                    for item in sorted_items
                ],
            }
        )

    return {
        "campaign_id": campaign_id,
        "items": items_tree,
    }


@router.post("", status_code=201)
def create_component(
    campaign_id: int,
    payload: ComponentCreate,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    require_campaign(db, campaign_id)

    duplicate = (
        db.query(CampaignComponent)
        .filter(
            CampaignComponent.campaign_id == campaign_id,
            CampaignComponent.component_key == payload.component_key.strip(),
        )
        .first()
    )

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
        display_order=payload.display_order,
    )
    db.add(component)
    db.commit()
    db.refresh(component)

    config = resolve_config()
    persist_campaign_yaml_session_or_raise(db, config, campaign_id)

    return {"id": component.id, "campaign_id": campaign_id, **payload.model_dump()}


@router.patch("/{component_id}")
def update_component(
    campaign_id: int,
    component_id: int,
    payload: ComponentUpdate,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No component fields provided")

    require_campaign(db, campaign_id)
    component = (
        db.query(CampaignComponent)
        .filter(
            CampaignComponent.id == component_id,
            CampaignComponent.campaign_id == campaign_id,
        )
        .first()
    )

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


@router.delete("/{component_id}", status_code=204)
def delete_component(
    campaign_id: int,
    component_id: int,
    db: Session = Depends(get_db_session),
) -> None:
    require_campaign(db, campaign_id)
    component = (
        db.query(CampaignComponent)
        .filter(
            CampaignComponent.id == component_id,
            CampaignComponent.campaign_id == campaign_id,
        )
        .first()
    )

    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")

    db.delete(component)
    db.commit()

    config = resolve_config()
    persist_campaign_yaml_session_or_raise(db, config, campaign_id)


@router.post("/{component_id}/items", status_code=201)
def create_component_item(
    campaign_id: int,
    component_id: int,
    payload: ComponentItemCreate,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    require_campaign(db, campaign_id)
    component = (
        db.query(CampaignComponent)
        .filter(
            CampaignComponent.id == component_id,
            CampaignComponent.campaign_id == campaign_id,
        )
        .first()
    )
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
        display_order=payload.display_order,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    config = resolve_config()
    persist_campaign_yaml_session_or_raise(db, config, campaign_id)

    return {"id": item.id, "component_id": component_id, **payload.model_dump()}


@router.patch("/{component_id}/items/{item_id}")
def update_component_item(
    campaign_id: int,
    component_id: int,
    item_id: int,
    payload: ComponentItemUpdate,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No item fields provided")

    require_campaign(db, campaign_id)
    item = (
        db.query(CampaignComponentItem)
        .join(CampaignComponent)
        .filter(
            CampaignComponentItem.id == item_id,
            CampaignComponentItem.component_id == component_id,
            CampaignComponent.campaign_id == campaign_id,
        )
        .first()
    )

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


@router.delete("/{component_id}/items/{item_id}", status_code=204)
def delete_component_item(
    campaign_id: int,
    component_id: int,
    item_id: int,
    db: Session = Depends(get_db_session),
) -> None:
    require_campaign(db, campaign_id)
    item = (
        db.query(CampaignComponentItem)
        .join(CampaignComponent)
        .filter(
            CampaignComponentItem.id == item_id,
            CampaignComponentItem.component_id == component_id,
            CampaignComponent.campaign_id == campaign_id,
        )
        .first()
    )

    if item is None:
        raise HTTPException(status_code=404, detail="Component item not found")

    db.delete(item)
    db.commit()

    config = resolve_config()
    persist_campaign_yaml_session_or_raise(db, config, campaign_id)
