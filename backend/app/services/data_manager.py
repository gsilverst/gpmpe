from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Business, Campaign, CampaignTemplateBinding


def list_business_summaries(db: Session) -> list[dict[str, Any]]:
    rows = db.query(Business).order_by(Business.display_name.asc()).all()
    return [
        {
            "display_name": row.display_name,
            "legal_name": row.legal_name,
            "timezone": row.timezone,
            "is_active": row.is_active,
        }
        for row in rows
    ]


def business_snapshot(db: Session, display_name: str) -> dict[str, Any]:
    business = db.query(Business).filter(Business.display_name == display_name).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    theme = next((t for t in business.brand_themes if t.name == "default"), None)

    return {
        "display_name": business.display_name,
        "legal_name": business.legal_name,
        "timezone": business.timezone,
        "is_active": business.is_active,
        "contacts": [
            {
                "contact_type": c.contact_type,
                "contact_value": c.contact_value,
                "is_primary": c.is_primary,
            }
            for c in business.contacts
        ],
        "locations": [
            {
                "label": row.label,
                "line1": row.line1,
                "line2": row.line2,
                "city": row.city,
                "state": row.state,
                "postal_code": row.postal_code,
                "country": row.country,
                "hours": json.loads(row.hours_json or "{}"),
            }
            for row in business.locations
        ],
        "brand_theme": {
            "name": theme.name,
            "primary_color": theme.primary_color,
            "secondary_color": theme.secondary_color,
            "accent_color": theme.accent_color,
            "font_family": theme.font_family,
            "logo_path": theme.logo_path,
        }
        if theme is not None
        else None,
    }


def list_campaign_summaries(db: Session, business_name: str) -> list[dict[str, Any]]:
    business = db.query(Business).filter(Business.display_name == business_name).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    campaigns = sorted(business.campaigns, key=lambda c: (c.campaign_name, c.campaign_key or ""))
    return [
        {
            "display_name": c.campaign_name,
            "campaign_name": c.campaign_name,
            "qualifier": c.campaign_key or None,
            "title": c.title,
            "objective": c.objective,
            "footnote_text": c.footnote_text,
            "status": c.status,
            "start_date": c.start_date,
            "end_date": c.end_date,
        }
        for c in campaigns
    ]


def campaign_snapshot(
    db: Session,
    display_name: str,
    campaign_name: str,
    qualifier: str | None,
) -> dict[str, Any]:
    business = db.query(Business).filter(Business.display_name == display_name).first()
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    campaign = (
        db.query(Campaign)
        .filter(
            Campaign.business_id == business.id,
            Campaign.campaign_name == campaign_name,
            Campaign.campaign_key == (qualifier or ""),
        )
        .first()
    )

    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    sorted_offers = sorted(campaign.offers, key=lambda o: (o.start_date or "", o.id))
    sorted_components = sorted(campaign.components, key=lambda c: (c.display_order, c.id))

    binding = (
        db.query(CampaignTemplateBinding)
        .filter(
            CampaignTemplateBinding.campaign_id == campaign.id,
            CampaignTemplateBinding.is_active == True,
        )
        .order_by(CampaignTemplateBinding.id.desc())
        .first()
    )

    component_payloads: list[dict[str, Any]] = []
    for component in sorted_components:
        sorted_items = sorted(component.items, key=lambda i: (i.display_order, i.id))
        component_payloads.append(
            {
                "component_key": component.component_key,
                "component_kind": component.component_kind,
                "render_region": component.render_region,
                "render_mode": component.render_mode,
                "style": json.loads(component.style_json or "{}"),
                "display_title": component.display_title,
                "footnote_text": component.footnote_text,
                "subtitle": component.subtitle,
                "description_text": component.description_text,
                "display_order": component.display_order,
                "items": [
                    {
                        "item_name": item.item_name,
                        "item_kind": item.item_kind,
                        "duration_label": item.duration_label,
                        "item_value": item.item_value,
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
        "id": campaign.id,
        "display_name": campaign.campaign_name,
        "campaign_name": campaign.campaign_name,
        "qualifier": campaign.campaign_key or None,
        "title": campaign.title,
        "objective": campaign.objective,
        "footnote_text": campaign.footnote_text,
        "status": campaign.status,
        "start_date": campaign.start_date,
        "end_date": campaign.end_date,
        "offers": [
            {
                "offer_name": item.offer_name,
                "offer_type": item.offer_type,
                "offer_value": item.offer_value,
                "start_date": item.start_date,
                "end_date": item.end_date,
                "terms_text": item.terms_text,
            }
            for item in sorted_offers
        ],
        "assets": [
            {
                "asset_type": item.asset_type,
                "source_type": item.source_type,
                "mime_type": item.mime_type,
                "source_path": item.source_path,
                "width": item.width,
                "height": item.height,
                "metadata": json.loads(item.metadata_json or "{}"),
            }
            for item in campaign.assets
        ],
        "components": component_payloads,
        "template_binding": {
            "template_name": binding.template.template_name,
            "template_kind": binding.template.template_kind,
            "size_spec": binding.template.size_spec,
            "layout": json.loads(binding.template.layout_json or "{}"),
            "default_values": json.loads(binding.template.default_values_json or "{}"),
            "override_values": json.loads(binding.override_values_json or "{}"),
        }
        if binding is not None
        else None,
    }
