from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from typing import Any

import yaml
from sqlalchemy.orm import Session

from .models import (
    BrandTheme,
    Business,
    BusinessContact,
    BusinessLocation,
    Campaign,
    CampaignAsset,
    CampaignComponent,
    CampaignComponentItem,
    CampaignOffer,
    CampaignTemplateBinding,
    TemplateDefinition,
)


SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class CampaignYamlRecord:
    directory_name: str
    file_path: Path
    payload: dict[str, Any]


@dataclass(frozen=True)
class BusinessYamlRecord:
    directory_name: str
    file_path: Path
    payload: dict[str, Any]
    campaigns: list[CampaignYamlRecord]


@dataclass(frozen=True)
class SyncSummary:
    businesses_synced: int
    campaigns_synced: int


@dataclass(frozen=True)
class ReconciliationReport:
    in_sync: bool
    yaml_only: list[str]      # business display_names in YAML but not in DB
    db_only: list[str]        # business display_names in DB but not in YAML
    content_differs: list[str]  # names present in both but with different campaign sets
    db_latest_updated_at: str | None   # most recent DB updated_at (ISO string)
    yaml_latest_mtime: str | None      # most recent YAML file mtime (ISO string)


def _ensure_safe_name(name: str, kind: str) -> None:
    if not SAFE_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Unsafe {kind} name '{name}'. Use filesystem-safe names only in MVP.")


def _load_yaml_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML file must contain an object at top level: {path}")
    return payload


def _atomic_write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.dump(payload, handle, allow_unicode=True, sort_keys=False)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def _required_string(payload: dict[str, Any], field_name: str, path: Path) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"Missing required string field '{field_name}' in {path}")
    return value.strip()


def _optional_string(payload: dict[str, Any], field_name: str) -> str | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise ValueError(f"Field '{field_name}' must be a string when provided")
    stripped = value.strip()
    return stripped if stripped else None


def _component_render_defaults(component_kind: str | None) -> tuple[str | None, str | None]:
    defaults = {
        "featured-offers": ("featured", "offer-card-grid"),
        "weekday-specials": ("secondary", "strip-list"),
        "other-offers": ("secondary", "strip-list"),
        "secondary-offers": ("secondary", "strip-list"),
        "discount-strip": ("discount", "discount-panel"),
        "legal-note": ("legal", "legal-text"),
    }
    return defaults.get(component_kind or "", (None, None))


def discover_data_directory(data_dir: Path) -> list[BusinessYamlRecord]:
    businesses: list[BusinessYamlRecord] = []
    if not data_dir.exists():
        return businesses

    for business_dir in sorted(path for path in data_dir.iterdir() if path.is_dir()):
        business_name = business_dir.name
        business_yaml = business_dir / f"{business_name}.yaml"
        if not business_yaml.exists():
            # Ignore non-business directories in DATA_DIR (for example notes/).
            continue
        _ensure_safe_name(business_name, "business")
        business_payload = _load_yaml_file(business_yaml)

        campaign_records: list[CampaignYamlRecord] = []
        campaign_root = business_dir / "promotions"
        if not campaign_root.exists():
            campaign_root = business_dir
        for campaign_dir in sorted(path for path in campaign_root.iterdir() if path.is_dir()):
            campaign_name = campaign_dir.name
            campaign_yaml = campaign_dir / f"{campaign_name}.yaml"
            if not campaign_yaml.exists():
                # Ignore non-campaign subdirectories inside a business directory.
                continue
            _ensure_safe_name(campaign_name, "campaign")
            campaign_payload = _load_yaml_file(campaign_yaml)
            campaign_records.append(
                CampaignYamlRecord(
                    directory_name=campaign_name,
                    file_path=campaign_yaml,
                    payload=campaign_payload,
                )
            )

        businesses.append(
            BusinessYamlRecord(
                directory_name=business_name,
                file_path=business_yaml,
                payload=business_payload,
                campaigns=campaign_records,
            )
        )

    return businesses


def _sync_business(connection: sqlite3.Connection, record: BusinessYamlRecord) -> int:
    payload = record.payload
    display_name = _required_string(payload, "display_name", record.file_path)
    legal_name = _required_string(payload, "legal_name", record.file_path)
    timezone = _optional_string(payload, "timezone") or "America/New_York"
    is_active = 1 if payload.get("is_active", True) else 0

    row = connection.execute(
        "SELECT id FROM businesses WHERE display_name = ?;",
        (display_name,),
    ).fetchone()
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO businesses (legal_name, display_name, timezone, is_active)
            VALUES (?, ?, ?, ?);
            """,
            (legal_name, display_name, timezone, is_active),
        )
        business_id = int(cursor.lastrowid)
    else:
        business_id = int(row["id"])
        connection.execute(
            """
            UPDATE businesses
            SET legal_name = ?, display_name = ?, timezone = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?;
            """,
            (legal_name, display_name, timezone, is_active, business_id),
        )

    contacts = payload.get("contacts", []) or []
    if not isinstance(contacts, list):
        raise ValueError(f"contacts must be a list in {record.file_path}")
    connection.execute("DELETE FROM business_contacts WHERE business_id = ?;", (business_id,))
    for contact in contacts:
        if not isinstance(contact, dict):
            raise ValueError(f"contacts entries must be objects in {record.file_path}")
        contact_type = _required_string(contact, "contact_type", record.file_path)
        contact_value = _required_string(contact, "contact_value", record.file_path)
        is_primary = 1 if contact.get("is_primary", False) else 0
        connection.execute(
            """
            INSERT INTO business_contacts (business_id, contact_type, contact_value, is_primary)
            VALUES (?, ?, ?, ?);
            """,
            (business_id, contact_type, contact_value, is_primary),
        )

    locations = payload.get("locations", []) or []
    if not isinstance(locations, list):
        raise ValueError(f"locations must be a list in {record.file_path}")
    connection.execute("DELETE FROM business_locations WHERE business_id = ?;", (business_id,))
    for location in locations:
        if not isinstance(location, dict):
            raise ValueError(f"locations entries must be objects in {record.file_path}")
        connection.execute(
            """
            INSERT INTO business_locations (
              business_id, label, line1, line2, city, state, postal_code, country, hours_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                business_id,
                _optional_string(location, "label"),
                _required_string(location, "line1", record.file_path),
                _optional_string(location, "line2"),
                _required_string(location, "city", record.file_path),
                _required_string(location, "state", record.file_path),
                _required_string(location, "postal_code", record.file_path),
                _optional_string(location, "country") or "US",
                json.dumps(location.get("hours") or {}),
            ),
        )

    brand_theme = payload.get("brand_theme") or {}
    if not isinstance(brand_theme, dict):
        raise ValueError(f"brand_theme must be an object in {record.file_path}")
    theme_name = _optional_string(brand_theme, "name") or "default"
    connection.execute(
        "DELETE FROM brand_themes WHERE business_id = ? AND name != ?;",
        (business_id, theme_name),
    )
    connection.execute(
        """
        INSERT INTO brand_themes (
          business_id, name, primary_color, secondary_color, accent_color, font_family, logo_path
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (business_id, name)
        DO UPDATE SET
          primary_color = excluded.primary_color,
          secondary_color = excluded.secondary_color,
          accent_color = excluded.accent_color,
          font_family = excluded.font_family,
          logo_path = excluded.logo_path,
          updated_at = CURRENT_TIMESTAMP;
        """,
        (
            business_id,
            theme_name,
            _optional_string(brand_theme, "primary_color"),
            _optional_string(brand_theme, "secondary_color"),
            _optional_string(brand_theme, "accent_color"),
            _optional_string(brand_theme, "font_family"),
            _optional_string(brand_theme, "logo_path"),
        ),
    )

    return business_id


def _reconcile_campaigns(
    connection: sqlite3.Connection, business_id: int, campaign_records: list[CampaignYamlRecord]
) -> None:
    expected_campaigns = {
        (
            _required_string(record.payload, "campaign_name", record.file_path),
            _optional_string(record.payload, "qualifier") or "",
        )
        for record in campaign_records
    }
    rows = connection.execute(
        "SELECT id, campaign_name, campaign_key FROM campaigns WHERE business_id = ?;",
        (business_id,),
    ).fetchall()
    for row in rows:
        if (row["campaign_name"], row["campaign_key"] or "") not in expected_campaigns:
            connection.execute("DELETE FROM campaigns WHERE id = ?;", (row["id"],))


def _reconcile_businesses(connection: sqlite3.Connection, business_records: list[BusinessYamlRecord]) -> None:
    expected_businesses = {
        _required_string(record.payload, "display_name", record.file_path) for record in business_records
    }
    rows = connection.execute("SELECT id, display_name FROM businesses;").fetchall()
    for row in rows:
        if row["display_name"] not in expected_businesses:
            connection.execute("DELETE FROM businesses WHERE id = ?;", (row["id"],))


def _delete_orphaned_template_definitions(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        DELETE FROM template_definitions
        WHERE id NOT IN (
          SELECT DISTINCT template_id FROM campaign_template_bindings
        );
        """
    )


def _sync_campaign_components(connection: sqlite3.Connection, campaign_id: int, record: CampaignYamlRecord) -> None:
    components = record.payload.get("components", []) or []
    if not isinstance(components, list):
        raise ValueError(f"components must be a list in {record.file_path}")

    connection.execute("DELETE FROM campaign_components WHERE campaign_id = ?;", (campaign_id,))
    for component_index, component in enumerate(components):
        if not isinstance(component, dict):
            raise ValueError(f"components entries must be objects in {record.file_path}")
        component_kind = _optional_string(component, "component_kind") or "featured-offers"
        default_region, default_mode = _component_render_defaults(component_kind)

        cursor = connection.execute(
            """
            INSERT INTO campaign_components (
                            campaign_id, component_key, component_kind, render_region, render_mode, style_json, display_title, background_color, header_accent_color, footnote_text, subtitle, description_text, display_order
            )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                campaign_id,
                _required_string(component, "component_key", record.file_path),
                component_kind,
                _optional_string(component, "render_region") or default_region,
                _optional_string(component, "render_mode") or default_mode,
                json.dumps(component.get("style") or component.get("style_json") or {}),
                _required_string(component, "display_title", record.file_path),
                _optional_string(component, "background_color"),
                _optional_string(component, "header_accent_color"),
                                _optional_string(component, "footnote_text"),
                _optional_string(component, "subtitle"),
                _optional_string(component, "description_text"),
                component.get("display_order", component_index),
            ),
        )
        component_id = int(cursor.lastrowid)

        items = component.get("items", []) or []
        if not isinstance(items, list):
            raise ValueError(f"component items must be a list in {record.file_path}")

        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"component items entries must be objects in {record.file_path}")
            connection.execute(
                """
                INSERT INTO campaign_component_items (
                  component_id, item_name, item_kind, duration_label, item_value,
                                    background_color, render_role, style_json, description_text, terms_text, display_order
                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    component_id,
                    _required_string(item, "item_name", record.file_path),
                    _optional_string(item, "item_kind") or "service",
                    _optional_string(item, "duration_label"),
                    _optional_string(item, "item_value"),
                                        _optional_string(item, "background_color"),
                    _optional_string(item, "render_role"),
                    json.dumps(item.get("style") or item.get("style_json") or {}),
                    _optional_string(item, "description_text"),
                    _optional_string(item, "terms_text"),
                    item.get("display_order", item_index),
                ),
            )


def _sync_campaign(connection: sqlite3.Connection, business_id: int, record: CampaignYamlRecord) -> None:
    payload = record.payload
    campaign_name = _required_string(payload, "campaign_name", record.file_path)
    qualifier = _optional_string(payload, "qualifier") or ""
    title = _required_string(payload, "title", record.file_path)
    objective = _optional_string(payload, "objective")
    footnote_text = _optional_string(payload, "footnote_text")
    status = _optional_string(payload, "status") or "draft"
    start_date = _optional_string(payload, "start_date")
    end_date = _optional_string(payload, "end_date")
    display_name = _optional_string(payload, "display_name") or record.directory_name

    row = connection.execute(
        """
        SELECT id FROM campaigns
        WHERE business_id = ? AND campaign_name = ? AND campaign_key = ?;
        """,
        (business_id, campaign_name, qualifier),
    ).fetchone()
    if row is None:
        cursor = connection.execute(
            """
            INSERT INTO campaigns (
                            business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date, details_json
            )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                business_id,
                campaign_name,
                qualifier,
                title,
                objective,
                                footnote_text,
                status,
                start_date,
                end_date,
                json.dumps({"display_name": display_name}),
            ),
        )
        campaign_id = int(cursor.lastrowid)
    else:
        campaign_id = int(row["id"])
        connection.execute(
            """
            UPDATE campaigns
            SET title = ?, objective = ?, footnote_text = ?, status = ?, start_date = ?, end_date = ?, details_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?;
            """,
            (
                title,
                objective,
                footnote_text,
                status,
                start_date,
                end_date,
                json.dumps({"display_name": display_name}),
                campaign_id,
            ),
        )

    offers = payload.get("offers", []) or []
    if not isinstance(offers, list):
        raise ValueError(f"offers must be a list in {record.file_path}")
    connection.execute("DELETE FROM campaign_offers WHERE campaign_id = ?;", (campaign_id,))
    for offer in offers:
        if not isinstance(offer, dict):
            raise ValueError(f"offers entries must be objects in {record.file_path}")
        connection.execute(
            """
            INSERT INTO campaign_offers (
              campaign_id, offer_name, offer_type, offer_value, start_date, end_date, terms_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                campaign_id,
                _required_string(offer, "offer_name", record.file_path),
                _optional_string(offer, "offer_type") or "discount",
                _optional_string(offer, "offer_value"),
                _optional_string(offer, "start_date"),
                _optional_string(offer, "end_date"),
                _optional_string(offer, "terms_text"),
            ),
        )

    _sync_campaign_components(connection, campaign_id, record)

    assets = payload.get("assets", []) or []
    if not isinstance(assets, list):
        raise ValueError(f"assets must be a list in {record.file_path}")
    connection.execute("DELETE FROM campaign_assets WHERE campaign_id = ?;", (campaign_id,))
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError(f"assets entries must be objects in {record.file_path}")
        connection.execute(
            """
            INSERT INTO campaign_assets (
              campaign_id, asset_type, source_type, mime_type, source_path, width, height, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                campaign_id,
                _required_string(asset, "asset_type", record.file_path),
                _required_string(asset, "source_type", record.file_path),
                _required_string(asset, "mime_type", record.file_path),
                _required_string(asset, "source_path", record.file_path),
                asset.get("width"),
                asset.get("height"),
                json.dumps(asset.get("metadata") or {}),
            ),
        )

    connection.execute("DELETE FROM campaign_template_bindings WHERE campaign_id = ?;", (campaign_id,))

    binding = payload.get("template_binding") or {}
    if binding:
        if not isinstance(binding, dict):
            raise ValueError(f"template_binding must be an object in {record.file_path}")
        template_name = _required_string(binding, "template_name", record.file_path)
        template_kind = _required_string(binding, "template_kind", record.file_path)
        size_spec = _optional_string(binding, "size_spec")
        layout = binding.get("layout") or {}
        default_values = binding.get("default_values") or {}
        override_values = binding.get("override_values") or {}

        template_row = connection.execute(
            "SELECT id FROM template_definitions WHERE template_name = ?;",
            (template_name,),
        ).fetchone()
        if template_row is None:
            cursor = connection.execute(
                """
                INSERT INTO template_definitions (
                  template_name, template_kind, size_spec, layout_json, default_values_json
                )
                VALUES (?, ?, ?, ?, ?);
                """,
                (template_name, template_kind, size_spec, json.dumps(layout), json.dumps(default_values)),
            )
            template_id = int(cursor.lastrowid)
        else:
            template_id = int(template_row["id"])
            connection.execute(
                """
                UPDATE template_definitions
                SET template_kind = ?, size_spec = ?, layout_json = ?, default_values_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
                """,
                (template_kind, size_spec, json.dumps(layout), json.dumps(default_values), template_id),
            )
        connection.execute(
            """
            INSERT INTO campaign_template_bindings (campaign_id, template_id, override_values_json, is_active)
            VALUES (?, ?, ?, 1);
            """,
            (campaign_id, template_id, json.dumps(override_values)),
        )


def sync_data_directory(connection: sqlite3.Connection, data_dir: Path) -> SyncSummary:
    records = discover_data_directory(data_dir)
    campaigns_synced = 0
    for business_record in records:
        business_id = _sync_business(connection, business_record)
        _reconcile_campaigns(connection, business_id, business_record.campaigns)
        for campaign_record in business_record.campaigns:
            _sync_campaign(connection, business_id, campaign_record)
            campaigns_synced += 1
    _reconcile_businesses(connection, records)
    _delete_orphaned_template_definitions(connection)
    return SyncSummary(businesses_synced=len(records), campaigns_synced=campaigns_synced)


def _sync_business_session(db: Session, record: BusinessYamlRecord) -> int:
    payload = record.payload
    display_name = _required_string(payload, "display_name", record.file_path)
    legal_name = _required_string(payload, "legal_name", record.file_path)
    timezone = _optional_string(payload, "timezone") or "America/New_York"
    is_active = bool(payload.get("is_active", True))

    business = db.query(Business).filter(Business.display_name == display_name).first()
    if business is None:
        business = Business(
            legal_name=legal_name,
            display_name=display_name,
            timezone=timezone,
            is_active=is_active,
        )
        db.add(business)
        db.flush()
    else:
        business.legal_name = legal_name
        business.display_name = display_name
        business.timezone = timezone
        business.is_active = is_active

    contacts = payload.get("contacts", []) or []
    if not isinstance(contacts, list):
        raise ValueError(f"contacts must be a list in {record.file_path}")
    business.contacts.clear()
    for contact in contacts:
        if not isinstance(contact, dict):
            raise ValueError(f"contacts entries must be objects in {record.file_path}")
        business.contacts.append(
            BusinessContact(
                contact_type=_required_string(contact, "contact_type", record.file_path),
                contact_value=_required_string(contact, "contact_value", record.file_path),
                is_primary=bool(contact.get("is_primary", False)),
            )
        )

    locations = payload.get("locations", []) or []
    if not isinstance(locations, list):
        raise ValueError(f"locations must be a list in {record.file_path}")
    business.locations.clear()
    for location in locations:
        if not isinstance(location, dict):
            raise ValueError(f"locations entries must be objects in {record.file_path}")
        business.locations.append(
            BusinessLocation(
                label=_optional_string(location, "label"),
                line1=_required_string(location, "line1", record.file_path),
                line2=_optional_string(location, "line2"),
                city=_required_string(location, "city", record.file_path),
                state=_required_string(location, "state", record.file_path),
                postal_code=_required_string(location, "postal_code", record.file_path),
                country=_optional_string(location, "country") or "US",
                hours_json=json.dumps(location.get("hours") or {}),
            )
        )

    brand_theme = payload.get("brand_theme") or {}
    if not isinstance(brand_theme, dict):
        raise ValueError(f"brand_theme must be an object in {record.file_path}")
    theme_name = _optional_string(brand_theme, "name") or "default"
    for theme in list(business.brand_themes):
        if theme.name != theme_name:
            db.delete(theme)
    theme = next((row for row in business.brand_themes if row.name == theme_name), None)
    if theme is None:
        theme = BrandTheme(name=theme_name)
        business.brand_themes.append(theme)
    theme.primary_color = _optional_string(brand_theme, "primary_color")
    theme.secondary_color = _optional_string(brand_theme, "secondary_color")
    theme.accent_color = _optional_string(brand_theme, "accent_color")
    theme.font_family = _optional_string(brand_theme, "font_family")
    theme.logo_path = _optional_string(brand_theme, "logo_path")
    db.flush()
    return business.id


def _reconcile_campaigns_session(
    db: Session,
    business_id: int,
    campaign_records: list[CampaignYamlRecord],
) -> None:
    expected_campaigns = {
        (
            _required_string(record.payload, "campaign_name", record.file_path),
            _optional_string(record.payload, "qualifier") or "",
        )
        for record in campaign_records
    }
    rows = db.query(Campaign).filter(Campaign.business_id == business_id).all()
    for row in rows:
        if (row.campaign_name, row.campaign_key or "") not in expected_campaigns:
            db.delete(row)


def _reconcile_businesses_session(db: Session, business_records: list[BusinessYamlRecord]) -> None:
    expected_businesses = {
        _required_string(record.payload, "display_name", record.file_path) for record in business_records
    }
    rows = db.query(Business).all()
    for row in rows:
        if row.display_name not in expected_businesses:
            db.delete(row)


def _delete_orphaned_template_definitions_session(db: Session) -> None:
    db.flush()
    templates = db.query(TemplateDefinition).filter(~TemplateDefinition.bindings.any()).all()
    for template in templates:
        db.delete(template)


def _sync_campaign_components_session(db: Session, campaign: Campaign, record: CampaignYamlRecord) -> None:
    components = record.payload.get("components", []) or []
    if not isinstance(components, list):
        raise ValueError(f"components must be a list in {record.file_path}")

    campaign.components.clear()
    db.flush()
    for component_index, component in enumerate(components):
        if not isinstance(component, dict):
            raise ValueError(f"components entries must be objects in {record.file_path}")
        component_kind = _optional_string(component, "component_kind") or "featured-offers"
        default_region, default_mode = _component_render_defaults(component_kind)
        component_model = CampaignComponent(
            component_key=_required_string(component, "component_key", record.file_path),
            component_kind=component_kind,
            render_region=_optional_string(component, "render_region") or default_region,
            render_mode=_optional_string(component, "render_mode") or default_mode,
            style_json=json.dumps(component.get("style") or component.get("style_json") or {}),
            display_title=_required_string(component, "display_title", record.file_path),
            background_color=_optional_string(component, "background_color"),
            header_accent_color=_optional_string(component, "header_accent_color"),
            footnote_text=_optional_string(component, "footnote_text"),
            subtitle=_optional_string(component, "subtitle"),
            description_text=_optional_string(component, "description_text"),
            display_order=component.get("display_order", component_index),
        )
        campaign.components.append(component_model)

        items = component.get("items", []) or []
        if not isinstance(items, list):
            raise ValueError(f"component items must be a list in {record.file_path}")
        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"component items entries must be objects in {record.file_path}")
            component_model.items.append(
                CampaignComponentItem(
                    item_name=_required_string(item, "item_name", record.file_path),
                    item_kind=_optional_string(item, "item_kind") or "service",
                    duration_label=_optional_string(item, "duration_label"),
                    item_value=_optional_string(item, "item_value"),
                    background_color=_optional_string(item, "background_color"),
                    render_role=_optional_string(item, "render_role"),
                    style_json=json.dumps(item.get("style") or item.get("style_json") or {}),
                    description_text=_optional_string(item, "description_text"),
                    terms_text=_optional_string(item, "terms_text"),
                    display_order=item.get("display_order", item_index),
                )
            )


def _sync_campaign_session(db: Session, business_id: int, record: CampaignYamlRecord) -> None:
    payload = record.payload
    campaign_name = _required_string(payload, "campaign_name", record.file_path)
    qualifier = _optional_string(payload, "qualifier") or ""
    title = _required_string(payload, "title", record.file_path)
    display_name = _optional_string(payload, "display_name") or record.directory_name

    campaign = (
        db.query(Campaign)
        .filter(
            Campaign.business_id == business_id,
            Campaign.campaign_name == campaign_name,
            Campaign.campaign_key == qualifier,
        )
        .first()
    )
    if campaign is None:
        campaign = Campaign(
            business_id=business_id,
            campaign_name=campaign_name,
            campaign_key=qualifier,
            title=title,
        )
        db.add(campaign)
        db.flush()

    campaign.title = title
    campaign.objective = _optional_string(payload, "objective")
    campaign.footnote_text = _optional_string(payload, "footnote_text")
    campaign.status = _optional_string(payload, "status") or "draft"
    campaign.start_date = _optional_string(payload, "start_date")
    campaign.end_date = _optional_string(payload, "end_date")
    campaign.details_json = json.dumps({"display_name": display_name})

    offers = payload.get("offers", []) or []
    if not isinstance(offers, list):
        raise ValueError(f"offers must be a list in {record.file_path}")
    campaign.offers.clear()
    for offer in offers:
        if not isinstance(offer, dict):
            raise ValueError(f"offers entries must be objects in {record.file_path}")
        campaign.offers.append(
            CampaignOffer(
                offer_name=_required_string(offer, "offer_name", record.file_path),
                offer_type=_optional_string(offer, "offer_type") or "discount",
                offer_value=_optional_string(offer, "offer_value"),
                start_date=_optional_string(offer, "start_date"),
                end_date=_optional_string(offer, "end_date"),
                terms_text=_optional_string(offer, "terms_text"),
            )
        )

    _sync_campaign_components_session(db, campaign, record)

    assets = payload.get("assets", []) or []
    if not isinstance(assets, list):
        raise ValueError(f"assets must be a list in {record.file_path}")
    campaign.assets.clear()
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError(f"assets entries must be objects in {record.file_path}")
        campaign.assets.append(
            CampaignAsset(
                asset_type=_required_string(asset, "asset_type", record.file_path),
                source_type=_required_string(asset, "source_type", record.file_path),
                mime_type=_required_string(asset, "mime_type", record.file_path),
                source_path=_required_string(asset, "source_path", record.file_path),
                width=asset.get("width"),
                height=asset.get("height"),
                metadata_json=json.dumps(asset.get("metadata") or {}),
            )
        )

    campaign.template_bindings.clear()
    binding = payload.get("template_binding") or {}
    if binding:
        if not isinstance(binding, dict):
            raise ValueError(f"template_binding must be an object in {record.file_path}")
        template_name = _required_string(binding, "template_name", record.file_path)
        template_kind = _required_string(binding, "template_kind", record.file_path)
        size_spec = _optional_string(binding, "size_spec")
        layout = binding.get("layout") or {}
        default_values = binding.get("default_values") or {}
        override_values = binding.get("override_values") or {}

        template = (
            db.query(TemplateDefinition)
            .filter(TemplateDefinition.template_name == template_name)
            .first()
        )
        if template is None:
            template = TemplateDefinition(template_name=template_name, template_kind=template_kind)
            db.add(template)
            db.flush()
        template.template_kind = template_kind
        template.size_spec = size_spec
        template.layout_json = json.dumps(layout)
        template.default_values_json = json.dumps(default_values)
        campaign.template_bindings.append(
            CampaignTemplateBinding(
                template=template,
                override_values_json=json.dumps(override_values),
                is_active=True,
            )
        )


def sync_data_directory_session(db: Session, data_dir: Path) -> SyncSummary:
    records = discover_data_directory(data_dir)
    campaigns_synced = 0
    for business_record in records:
        business_id = _sync_business_session(db, business_record)
        _reconcile_campaigns_session(db, business_id, business_record.campaigns)
        for campaign_record in business_record.campaigns:
            _sync_campaign_session(db, business_id, campaign_record)
            campaigns_synced += 1
    _reconcile_businesses_session(db, records)
    _delete_orphaned_template_definitions_session(db)
    return SyncSummary(businesses_synced=len(records), campaigns_synced=campaigns_synced)


def clone_campaign_directory(
    connection: sqlite3.Connection,
    data_dir: Path,
    source_campaign_name: str,
    new_campaign_name: str,
    source_campaign_key: str | None = None,
    destination_directory_name: str | None = None,
    new_campaign_key: str | None = None,
    business_name: str | None = None,
    new_title: str | None = None,
) -> CampaignYamlRecord:
    """Copy a campaign YAML directory tree to a new slug name.

    Locates *source_campaign_name* under *data_dir* (optionally scoped to
    *business_name*).  Copies the directory, renames the YAML file, and
    updates ``campaign_name``, ``display_name``, and ``title`` inside it.
    Then syncs the new campaign into the database and returns the record.

    Raises ``ValueError`` if the source campaign cannot be found or the
    destination already exists.
    """
    _ensure_safe_name(new_campaign_name, "campaign")
    destination_directory = destination_directory_name or new_campaign_name
    _ensure_safe_name(destination_directory, "campaign")

    # Locate source directory
    source_dir: Path | None = None
    source_business_dir: Path | None = None
    source_campaign_root: Path | None = None
    for business_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        if business_name and business_dir.name.lower() != business_name.lower():
            continue
        campaign_root = business_dir / "promotions"
        if not campaign_root.exists():
            campaign_root = business_dir
        candidate = campaign_root / source_campaign_name
        candidate_yaml = candidate / f"{source_campaign_name}.yaml"
        if candidate.is_dir() and candidate_yaml.exists():
            if source_campaign_key is not None:
                candidate_payload = _load_yaml_file(candidate_yaml)
                candidate_key = _optional_string(candidate_payload, "qualifier") or ""
                if candidate_key != source_campaign_key:
                    continue
            source_dir = candidate
            source_business_dir = business_dir
            source_campaign_root = campaign_root
            break

    if source_dir is None or source_business_dir is None or source_campaign_root is None:
        raise ValueError(
            f"Source campaign '{source_campaign_name}' not found under '{data_dir}'"
            + (f" for business '{business_name}'" if business_name else "")
        )

    dest_dir = source_campaign_root / destination_directory
    if dest_dir.exists():
        raise ValueError(f"Destination '{dest_dir}' already exists")

    # Copy tree
    shutil.copytree(source_dir, dest_dir)

    # Rename the YAML file inside the copy
    old_yaml = dest_dir / f"{source_campaign_name}.yaml"
    new_yaml = dest_dir / f"{destination_directory}.yaml"
    old_yaml.rename(new_yaml)

    # Update campaign_name, display_name, and title inside the YAML
    payload = _load_yaml_file(new_yaml)
    payload["campaign_name"] = new_campaign_name
    payload["display_name"] = destination_directory
    payload["qualifier"] = (new_campaign_key or "").strip() or None
    if new_title:
        payload["title"] = new_title
    else:
        # Generate a title from the slug (replace hyphens/underscores with spaces, title-case)
        payload["title"] = new_campaign_name.replace("-", " ").replace("_", " ").title()

    _atomic_write_yaml(new_yaml, payload)

    # Sync the new campaign into the DB
    record = CampaignYamlRecord(
        directory_name=destination_directory,
        file_path=new_yaml,
        payload=payload,
    )
    business_yaml = source_business_dir / f"{source_business_dir.name}.yaml"
    business_payload = _load_yaml_file(business_yaml)
    business_record = BusinessYamlRecord(
        directory_name=source_business_dir.name,
        file_path=business_yaml,
        payload=business_payload,
        campaigns=[record],
    )
    business_id = _sync_business(connection, business_record)
    _sync_campaign(connection, business_id, record)

    return record


def clone_campaign_directory_session(
    db: Session,
    data_dir: Path,
    source_campaign_name: str,
    new_campaign_name: str,
    source_campaign_key: str | None = None,
    destination_directory_name: str | None = None,
    new_campaign_key: str | None = None,
    business_name: str | None = None,
    new_title: str | None = None,
) -> CampaignYamlRecord:
    """Copy a campaign YAML directory tree and sync the clone through SQLAlchemy."""
    _ensure_safe_name(new_campaign_name, "campaign")
    destination_directory = destination_directory_name or new_campaign_name
    _ensure_safe_name(destination_directory, "campaign")

    source_dir: Path | None = None
    source_business_dir: Path | None = None
    source_campaign_root: Path | None = None
    for business_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        if business_name and business_dir.name.lower() != business_name.lower():
            continue
        campaign_root = business_dir / "promotions"
        if not campaign_root.exists():
            campaign_root = business_dir
        candidate = campaign_root / source_campaign_name
        candidate_yaml = candidate / f"{source_campaign_name}.yaml"
        if candidate.is_dir() and candidate_yaml.exists():
            if source_campaign_key is not None:
                candidate_payload = _load_yaml_file(candidate_yaml)
                candidate_key = _optional_string(candidate_payload, "qualifier") or ""
                if candidate_key != source_campaign_key:
                    continue
            source_dir = candidate
            source_business_dir = business_dir
            source_campaign_root = campaign_root
            break

    if source_dir is None or source_business_dir is None or source_campaign_root is None:
        raise ValueError(
            f"Source campaign '{source_campaign_name}' not found under '{data_dir}'"
            + (f" for business '{business_name}'" if business_name else "")
        )

    dest_dir = source_campaign_root / destination_directory
    if dest_dir.exists():
        raise ValueError(f"Destination '{dest_dir}' already exists")

    shutil.copytree(source_dir, dest_dir)

    old_yaml = dest_dir / f"{source_campaign_name}.yaml"
    new_yaml = dest_dir / f"{destination_directory}.yaml"
    old_yaml.rename(new_yaml)

    payload = _load_yaml_file(new_yaml)
    payload["campaign_name"] = new_campaign_name
    payload["display_name"] = destination_directory
    payload["qualifier"] = (new_campaign_key or "").strip() or None
    if new_title:
        payload["title"] = new_title
    else:
        payload["title"] = new_campaign_name.replace("-", " ").replace("_", " ").title()

    _atomic_write_yaml(new_yaml, payload)

    record = CampaignYamlRecord(
        directory_name=destination_directory,
        file_path=new_yaml,
        payload=payload,
    )
    business_yaml = source_business_dir / f"{source_business_dir.name}.yaml"
    business_payload = _load_yaml_file(business_yaml)
    business_record = BusinessYamlRecord(
        directory_name=source_business_dir.name,
        file_path=business_yaml,
        payload=business_payload,
        campaigns=[record],
    )
    business_id = _sync_business_session(db, business_record)
    _sync_campaign_session(db, business_id, record)
    return record


def compare_db_to_yaml(connection: sqlite3.Connection, data_dir: Path) -> ReconciliationReport:
    """Compare DB state against DATA_DIR YAML files.

    Returns a :class:`ReconciliationReport` describing which businesses are
    present in only one side, which have differing campaign sets, and
    timestamp hints for determining which side is newer.
    """
    yaml_records = discover_data_directory(data_dir)

    # ── YAML side ──────────────────────────────────────────────────────────
    # Map display_name → set of "campaign_name:qualifier" keys
    yaml_businesses: dict[str, set[str]] = {}
    yaml_latest_mtime: float | None = None

    for record in yaml_records:
        display_name = str(record.payload.get("display_name") or record.directory_name)
        campaign_keys: set[str] = set()
        for camp in record.campaigns:
            cname = str(camp.payload.get("campaign_name") or camp.directory_name)
            qualifier = str(camp.payload.get("qualifier") or "")
            campaign_keys.add(f"{cname}:{qualifier}")
            cmtime = camp.file_path.stat().st_mtime
            if yaml_latest_mtime is None or cmtime > yaml_latest_mtime:
                yaml_latest_mtime = cmtime
        yaml_businesses[display_name] = campaign_keys
        bmtime = record.file_path.stat().st_mtime
        if yaml_latest_mtime is None or bmtime > yaml_latest_mtime:
            yaml_latest_mtime = bmtime

    # ── DB side ─────────────────────────────────────────────────────────────
    db_businesses: dict[str, set[str]] = {}
    db_latest_updated_at: str | None = None

    for biz_row in connection.execute(
        "SELECT id, display_name, updated_at FROM businesses ORDER BY id;"
    ).fetchall():
        biz_id = int(biz_row["id"])
        display_name = str(biz_row["display_name"])
        if biz_row["updated_at"] and (
            db_latest_updated_at is None or biz_row["updated_at"] > db_latest_updated_at
        ):
            db_latest_updated_at = biz_row["updated_at"]

        campaign_keys: set[str] = set()
        for camp_row in connection.execute(
            "SELECT campaign_name, campaign_key, updated_at FROM campaigns WHERE business_id = ?;",
            (biz_id,),
        ).fetchall():
            qualifier = camp_row["campaign_key"] or ""
            campaign_keys.add(f"{camp_row['campaign_name']}:{qualifier}")
            if camp_row["updated_at"] and (
                db_latest_updated_at is None or camp_row["updated_at"] > db_latest_updated_at
            ):
                db_latest_updated_at = camp_row["updated_at"]
        db_businesses[display_name] = campaign_keys

    # ── Comparison ─────────────────────────────────────────────────────────
    yaml_set = set(yaml_businesses)
    db_set = set(db_businesses)

    yaml_only = sorted(yaml_set - db_set)
    db_only = sorted(db_set - yaml_set)
    content_differs = [
        name for name in sorted(yaml_set & db_set)
        if yaml_businesses[name] != db_businesses[name]
    ]
    in_sync = not yaml_only and not db_only and not content_differs

    yaml_mtime_str = (
        datetime.fromtimestamp(yaml_latest_mtime).isoformat() if yaml_latest_mtime else None
    )

    return ReconciliationReport(
        in_sync=in_sync,
        yaml_only=yaml_only,
        db_only=db_only,
        content_differs=content_differs,
        db_latest_updated_at=db_latest_updated_at,
        yaml_latest_mtime=yaml_mtime_str,
    )


def compare_db_to_yaml_session(db: Session, data_dir: Path) -> ReconciliationReport:
    """Compare SQLAlchemy-managed DB state against DATA_DIR YAML files."""
    yaml_records = discover_data_directory(data_dir)

    yaml_businesses: dict[str, set[str]] = {}
    yaml_latest_mtime: float | None = None

    for record in yaml_records:
        display_name = str(record.payload.get("display_name") or record.directory_name)
        campaign_keys: set[str] = set()
        for camp in record.campaigns:
            cname = str(camp.payload.get("campaign_name") or camp.directory_name)
            qualifier = str(camp.payload.get("qualifier") or "")
            campaign_keys.add(f"{cname}:{qualifier}")
            cmtime = camp.file_path.stat().st_mtime
            if yaml_latest_mtime is None or cmtime > yaml_latest_mtime:
                yaml_latest_mtime = cmtime
        yaml_businesses[display_name] = campaign_keys
        bmtime = record.file_path.stat().st_mtime
        if yaml_latest_mtime is None or bmtime > yaml_latest_mtime:
            yaml_latest_mtime = bmtime

    db_businesses: dict[str, set[str]] = {}
    db_latest_updated_at: str | None = None

    businesses = db.query(Business).order_by(Business.id.asc()).all()
    for business in businesses:
        if business.updated_at:
            updated_at = business.updated_at.isoformat()
            if db_latest_updated_at is None or updated_at > db_latest_updated_at:
                db_latest_updated_at = updated_at

        campaign_keys: set[str] = set()
        campaigns = (
            db.query(Campaign)
            .filter(Campaign.business_id == business.id)
            .order_by(Campaign.id.asc())
            .all()
        )
        for campaign in campaigns:
            qualifier = campaign.campaign_key or ""
            campaign_keys.add(f"{campaign.campaign_name}:{qualifier}")
            if campaign.updated_at:
                updated_at = campaign.updated_at.isoformat()
                if db_latest_updated_at is None or updated_at > db_latest_updated_at:
                    db_latest_updated_at = updated_at
        db_businesses[business.display_name] = campaign_keys

    yaml_set = set(yaml_businesses)
    db_set = set(db_businesses)

    yaml_only = sorted(yaml_set - db_set)
    db_only = sorted(db_set - yaml_set)
    content_differs = [
        name for name in sorted(yaml_set & db_set)
        if yaml_businesses[name] != db_businesses[name]
    ]
    in_sync = not yaml_only and not db_only and not content_differs

    yaml_mtime_str = (
        datetime.fromtimestamp(yaml_latest_mtime).isoformat() if yaml_latest_mtime else None
    )

    return ReconciliationReport(
        in_sync=in_sync,
        yaml_only=yaml_only,
        db_only=db_only,
        content_differs=content_differs,
        db_latest_updated_at=db_latest_updated_at,
        yaml_latest_mtime=yaml_mtime_str,
    )
