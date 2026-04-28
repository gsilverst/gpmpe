from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
from typing import Any

import yaml


SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _filesystem_name(name: str) -> str:
    stripped = name.strip()
    if stripped == "":
        return "item"
    if SAFE_NAME_PATTERN.fullmatch(stripped):
        return stripped

    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", stripped).strip("-")
    return normalized or "item"


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


def _component_payloads(connection: sqlite3.Connection, campaign_id: int) -> list[dict[str, Any]]:
    components = connection.execute(
        """
        SELECT id, component_key, component_kind, display_title, background_color, header_accent_color, footnote_text, subtitle, description_text, display_order
        FROM campaign_components
        WHERE campaign_id = ?
        ORDER BY display_order ASC, id ASC;
        """,
        (campaign_id,),
    ).fetchall()

    payloads: list[dict[str, Any]] = []
    for component in components:
        items = connection.execute(
            """
            SELECT item_name, item_kind, duration_label, item_value, background_color, description_text, terms_text, display_order
            FROM campaign_component_items
            WHERE component_id = ?
            ORDER BY display_order ASC, id ASC;
            """,
            (component["id"],),
        ).fetchall()
        payloads.append(
            {
                "component_key": component["component_key"],
                "component_kind": component["component_kind"],
                "display_title": component["display_title"],
                "background_color": component["background_color"],
                "header_accent_color": component["header_accent_color"],
                "footnote_text": component["footnote_text"],
                "subtitle": component["subtitle"],
                "description_text": component["description_text"],
                "display_order": component["display_order"],
                "items": [
                    {
                        "item_name": item["item_name"],
                        "item_kind": item["item_kind"],
                        "duration_label": item["duration_label"],
                        "item_value": item["item_value"],
                        "background_color": item["background_color"],
                        "description_text": item["description_text"],
                        "terms_text": item["terms_text"],
                        "display_order": item["display_order"],
                    }
                    for item in items
                ],
            }
        )
    return payloads


def _campaign_payload(connection: sqlite3.Connection, campaign_id: int) -> tuple[str, dict[str, Any]]:
    campaign = connection.execute(
        """
        SELECT c.business_id, c.campaign_name, c.campaign_key, c.title, c.objective, c.footnote_text, c.status, c.start_date, c.end_date, c.details_json,
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
    components = _component_payloads(connection, campaign_id)

    payload: dict[str, Any] = {
        "display_name": campaign_display_name,
        "campaign_name": campaign["campaign_name"],
        "qualifier": campaign["campaign_key"] or None,
        "title": campaign["title"],
        "objective": campaign["objective"],
        "footnote_text": campaign["footnote_text"],
        "status": campaign["status"],
        "start_date": campaign["start_date"],
        "end_date": campaign["end_date"],
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
    if components:
        payload["components"] = components
    else:
        payload["offers"] = [
            {
                "offer_name": row["offer_name"],
                "offer_type": row["offer_type"],
                "offer_value": row["offer_value"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "terms_text": row["terms_text"],
            }
            for row in offers
        ]
    return campaign["business_display_name"], payload


def _campaign_yaml_paths(connection: sqlite3.Connection, data_dir: Path, campaign_id: int) -> tuple[Path, Path, int]:
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

    business_path_name = _filesystem_name(campaign["business_display_name"])
    campaign_path_name = _filesystem_name(campaign["campaign_name"])

    business_dir = data_dir / business_path_name
    campaign_dir = business_dir / campaign_path_name
    business_file = business_dir / f"{business_path_name}.yaml"
    campaign_file = campaign_dir / f"{campaign_path_name}.yaml"
    return business_file, campaign_file, int(campaign["business_id"])


def campaign_yaml_paths_for_id(connection: sqlite3.Connection, data_dir: Path, campaign_id: int) -> tuple[Path, Path]:
    business_file, campaign_file, _ = _campaign_yaml_paths(connection, data_dir, campaign_id)
    return business_file, campaign_file


def persist_yaml_state_for_campaign(connection: sqlite3.Connection, data_dir: Path, campaign_id: int) -> tuple[Path, Path]:
    business_file, campaign_file, business_id = _campaign_yaml_paths(connection, data_dir, campaign_id)

    business_payload = _business_payload(connection, business_id)
    _, campaign_payload = _campaign_payload(connection, campaign_id)

    business_dir = business_file.parent
    campaign_dir = campaign_file.parent
    business_dir.mkdir(parents=True, exist_ok=True)
    campaign_dir.mkdir(parents=True, exist_ok=True)

    business_file.write_text(yaml.safe_dump(business_payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
    campaign_file.write_text(yaml.safe_dump(campaign_payload, sort_keys=False, allow_unicode=False), encoding="utf-8")

    return business_file, campaign_file


def write_all_to_data_dir(connection: sqlite3.Connection, data_dir: Path) -> None:
    """Write all businesses and campaigns from the database to DATA_DIR YAML files.

    Used when the database is the authoritative source and DATA_DIR needs to be
    populated or overwritten to match it.
    """
    businesses = connection.execute(
        "SELECT id, display_name FROM businesses ORDER BY id;"
    ).fetchall()

    for business in businesses:
        business_id = int(business["id"])
        business_path_name = _filesystem_name(business["display_name"])
        business_dir = data_dir / business_path_name
        business_dir.mkdir(parents=True, exist_ok=True)
        business_file = business_dir / f"{business_path_name}.yaml"
        payload = _business_payload(connection, business_id)
        business_file.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )

        campaigns = connection.execute(
            "SELECT id FROM campaigns WHERE business_id = ? ORDER BY id;",
            (business_id,),
        ).fetchall()
        for campaign in campaigns:
            campaign_id = int(campaign["id"])
            _, camp_file, _ = _campaign_yaml_paths(connection, data_dir, campaign_id)
            _, camp_payload = _campaign_payload(connection, campaign_id)
            camp_file.parent.mkdir(parents=True, exist_ok=True)
            camp_file.write_text(
                yaml.safe_dump(camp_payload, sort_keys=False, allow_unicode=False),
                encoding="utf-8",
            )