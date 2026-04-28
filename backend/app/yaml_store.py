from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from typing import Any

import yaml


SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _ensure_safe_name(name: str, kind: str) -> None:
    if not SAFE_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Unsafe {kind} name '{name}'. Rename is required before writing YAML files.")


def _business_payload(connection: sqlite3.Connection, business_id: int) -> dict[str, Any]:
    business = connection.execute(
        """
        SELECT legal_name, display_name, timezone, is_active
        FROM businesses
        WHERE id = ?;
        """,
        (business_id,),
    ).fetchone()
    if business is None:
        raise ValueError("Business not found")

    contacts = connection.execute(
        """
        SELECT contact_type, contact_value, is_primary
        FROM business_contacts
        WHERE business_id = ?
        ORDER BY is_primary DESC, id ASC;
        """,
        (business_id,),
    ).fetchall()
    locations = connection.execute(
        """
        SELECT label, line1, line2, city, state, postal_code, country, hours_json
        FROM business_locations
        WHERE business_id = ?
        ORDER BY id ASC;
        """,
        (business_id,),
    ).fetchall()
    theme = connection.execute(
        """
        SELECT name, primary_color, secondary_color, accent_color, font_family, logo_path
        FROM brand_themes
        WHERE business_id = ? AND name = 'default';
        """,
        (business_id,),
    ).fetchone()

    payload: dict[str, Any] = {
        "display_name": business["display_name"],
        "legal_name": business["legal_name"],
        "timezone": business["timezone"],
        "is_active": bool(business["is_active"]),
        "contacts": [
            {
                "contact_type": row["contact_type"],
                "contact_value": row["contact_value"],
                "is_primary": bool(row["is_primary"]),
            }
            for row in contacts
        ],
        "locations": [
            {
                "label": row["label"],
                "line1": row["line1"],
                "line2": row["line2"],
                "city": row["city"],
                "state": row["state"],
                "postal_code": row["postal_code"],
                "country": row["country"],
                "hours": json.loads(row["hours_json"] or "{}"),
            }
            for row in locations
        ],
        "brand_theme": {
            "name": theme["name"],
            "primary_color": theme["primary_color"],
            "secondary_color": theme["secondary_color"],
            "accent_color": theme["accent_color"],
            "font_family": theme["font_family"],
            "logo_path": theme["logo_path"],
        }
        if theme is not None
        else {},
    }
    return payload


def _campaign_payload(connection: sqlite3.Connection, campaign_id: int) -> tuple[str, dict[str, Any]]:
    campaign = connection.execute(
        """
        SELECT c.business_id, c.campaign_name, c.campaign_key, c.title, c.objective, c.status, c.start_date, c.end_date, c.details_json,
               b.display_name AS business_display_name
        FROM campaigns c
        JOIN businesses b ON b.id = c.business_id
        WHERE c.id = ?;
        """,
        (campaign_id,),
    ).fetchone()
    if campaign is None:
        raise ValueError("Campaign not found")

    details = json.loads(campaign["details_json"] or "{}")
    campaign_display_name = details.get("display_name") or campaign["campaign_name"]

    offers = connection.execute(
        """
        SELECT offer_name, offer_type, offer_value, start_date, end_date, terms_text
        FROM campaign_offers
        WHERE campaign_id = ?
        ORDER BY id ASC;
        """,
        (campaign_id,),
    ).fetchall()
    assets = connection.execute(
        """
        SELECT asset_type, source_type, mime_type, source_path, width, height, metadata_json
        FROM campaign_assets
        WHERE campaign_id = ?
        ORDER BY id ASC;
        """,
        (campaign_id,),
    ).fetchall()
    binding = connection.execute(
        """
        SELECT t.template_name, t.template_kind, t.size_spec, t.layout_json, t.default_values_json, b.override_values_json
        FROM campaign_template_bindings b
        JOIN template_definitions t ON t.id = b.template_id
        WHERE b.campaign_id = ? AND b.is_active = 1
        ORDER BY b.id DESC
        LIMIT 1;
        """,
        (campaign_id,),
    ).fetchone()

    payload: dict[str, Any] = {
        "display_name": campaign_display_name,
        "campaign_name": campaign["campaign_name"],
        "qualifier": campaign["campaign_key"] or None,
        "title": campaign["title"],
        "objective": campaign["objective"],
        "status": campaign["status"],
        "start_date": campaign["start_date"],
        "end_date": campaign["end_date"],
        "offers": [
            {
                "offer_name": row["offer_name"],
                "offer_type": row["offer_type"],
                "offer_value": row["offer_value"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "terms_text": row["terms_text"],
            }
            for row in offers
        ],
        "assets": [
            {
                "asset_type": row["asset_type"],
                "source_type": row["source_type"],
                "mime_type": row["mime_type"],
                "source_path": row["source_path"],
                "width": row["width"],
                "height": row["height"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }
            for row in assets
        ],
        "template_binding": {
            "template_name": binding["template_name"],
            "template_kind": binding["template_kind"],
            "size_spec": binding["size_spec"],
            "layout": json.loads(binding["layout_json"] or "{}"),
            "default_values": json.loads(binding["default_values_json"] or "{}"),
            "override_values": json.loads(binding["override_values_json"] or "{}"),
        }
        if binding is not None
        else {},
    }
    return campaign["business_display_name"], payload


def persist_yaml_state_for_campaign(connection: sqlite3.Connection, data_dir: Path, campaign_id: int) -> None:
    campaign = connection.execute(
        """
        SELECT c.business_id, c.campaign_name, b.display_name AS business_display_name
        FROM campaigns c
        JOIN businesses b ON b.id = c.business_id
        WHERE c.id = ?;
        """,
        (campaign_id,),
    ).fetchone()
    if campaign is None:
        raise ValueError("Campaign not found")

    business_name = campaign["business_display_name"]
    campaign_name = campaign["campaign_name"]
    _ensure_safe_name(business_name, "business")
    _ensure_safe_name(campaign_name, "campaign")

    business_payload = _business_payload(connection, campaign["business_id"])
    _, campaign_payload = _campaign_payload(connection, campaign_id)

    business_dir = data_dir / business_name
    campaign_dir = business_dir / campaign_name
    business_dir.mkdir(parents=True, exist_ok=True)
    campaign_dir.mkdir(parents=True, exist_ok=True)

    business_file = business_dir / f"{business_name}.yaml"
    campaign_file = campaign_dir / f"{campaign_name}.yaml"

    business_file.write_text(yaml.safe_dump(business_payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
    campaign_file.write_text(yaml.safe_dump(campaign_payload, sort_keys=False, allow_unicode=False), encoding="utf-8")