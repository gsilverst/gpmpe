from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import resolve_config
from ..dependencies import get_db_session, require_campaign
from ..models import CampaignTemplateBinding, TemplateDefinition
from ..schemas import CampaignTemplateBindingCreate, TemplateDefinitionCreate
from ..services.yaml_persistence import persist_campaign_yaml_session_or_raise

router = APIRouter()


@router.post("/templates", status_code=201)
def create_template(
    payload: TemplateDefinitionCreate,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    duplicate = (
        db.query(TemplateDefinition)
        .filter(TemplateDefinition.template_name == payload.template_name.strip())
        .first()
    )

    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Template name already exists")

    template = TemplateDefinition(
        template_name=payload.template_name.strip(),
        template_kind=payload.template_kind.strip(),
        size_spec=payload.size_spec,
        layout_json=json.dumps(payload.layout or {}),
        default_values_json=json.dumps(payload.default_values or {}),
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


@router.get("/templates")
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


@router.post("/campaigns/{campaign_id}/template-bindings", status_code=201)
def create_template_binding(
    campaign_id: int,
    payload: CampaignTemplateBindingCreate,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    require_campaign(db, campaign_id)

    template = db.get(TemplateDefinition, payload.template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    db.query(CampaignTemplateBinding).filter(
        CampaignTemplateBinding.campaign_id == campaign_id
    ).update({"is_active": False})

    binding = CampaignTemplateBinding(
        campaign_id=campaign_id,
        template_id=payload.template_id,
        override_values_json=json.dumps(payload.override_values or {}),
        is_active=True,
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


@router.get("/campaigns/{campaign_id}/template-binding/effective")
def get_effective_template_binding(
    campaign_id: int,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    require_campaign(db, campaign_id)

    binding = (
        db.query(CampaignTemplateBinding)
        .filter(
            CampaignTemplateBinding.campaign_id == campaign_id,
            CampaignTemplateBinding.is_active == True,
        )
        .order_by(CampaignTemplateBinding.id.desc())
        .first()
    )

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
