from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from fpdf import FPDF

# Letter-size in mm
_PAGE_W = 215.9
_PAGE_H = 279.4
_MARGIN = 20.0
_CONTENT_W = _PAGE_W - 2 * _MARGIN

# Brand fallbacks
_DEFAULT_PRIMARY = "#209dd7"
_DEFAULT_ACCENT = "#ecad0a"
_DEFAULT_INK = "#032147"


def _hex_to_rgb(hex_color: str | None, fallback: str) -> tuple[int, int, int]:
    raw = (hex_color or fallback).lstrip("#")
    try:
        r = int(raw[0:2], 16)
        g = int(raw[2:4], 16)
        b = int(raw[4:6], 16)
        return r, g, b
    except (ValueError, IndexError):
        raw = fallback.lstrip("#")
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def _fallback_components(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not offers:
        return []
    return [
        {
            "component_key": "offers",
            "component_kind": "featured-offers",
            "display_title": "Offer Details",
            "subtitle": None,
            "description_text": None,
            "display_order": 0,
            "items": [
                {
                    "item_name": offer.get("offer_name"),
                    "item_kind": offer.get("offer_type") or "service",
                    "duration_label": None,
                    "item_value": offer.get("offer_value"),
                    "description_text": None,
                    "terms_text": offer.get("terms_text"),
                    "display_order": index,
                    "start_date": offer.get("start_date"),
                    "end_date": offer.get("end_date"),
                }
                for index, offer in enumerate(offers)
            ],
        }
    ]


def _collect_render_context(connection: sqlite3.Connection, campaign_id: int) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT c.id, c.campaign_name, c.campaign_key, c.title, c.objective,
               c.status, c.start_date, c.end_date,
               b.display_name AS business_display_name,
               b.legal_name   AS business_legal_name,
               b.id           AS business_id
        FROM campaigns c
        JOIN businesses b ON b.id = c.business_id
        WHERE c.id = ?;
        """,
        (campaign_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Campaign {campaign_id} not found")

    business_id = row["business_id"]

    theme = connection.execute(
        """
        SELECT primary_color, secondary_color, accent_color, font_family, logo_path
        FROM brand_themes
        WHERE business_id = ? AND name = 'default';
        """,
        (business_id,),
    ).fetchone()

    location = connection.execute(
        """
        SELECT line1, line2, city, state, postal_code
        FROM business_locations
        WHERE business_id = ?
        ORDER BY id ASC LIMIT 1;
        """,
        (business_id,),
    ).fetchone()

    contacts = connection.execute(
        """
        SELECT contact_type, contact_value, is_primary
        FROM business_contacts
        WHERE business_id = ?
        ORDER BY is_primary DESC, id ASC;
        """,
        (business_id,),
    ).fetchall()

    offers = connection.execute(
        """
        SELECT offer_name, offer_type, offer_value, start_date, end_date, terms_text
        FROM campaign_offers
        WHERE campaign_id = ?
        ORDER BY id ASC;
        """,
        (campaign_id,),
    ).fetchall()
    components = connection.execute(
        """
        SELECT id, component_key, component_kind, display_title, subtitle, description_text, display_order
        FROM campaign_components
        WHERE campaign_id = ?
        ORDER BY display_order ASC, id ASC;
        """,
        (campaign_id,),
    ).fetchall()

    binding = connection.execute(
        """
        SELECT t.template_name, t.template_kind, t.size_spec,
               t.default_values_json, b.override_values_json
        FROM campaign_template_bindings b
        JOIN template_definitions t ON t.id = b.template_id
        WHERE b.campaign_id = ? AND b.is_active = 1
        ORDER BY b.id DESC LIMIT 1;
        """,
        (campaign_id,),
    ).fetchone()

    effective: dict[str, Any] = {}
    template_name = None
    if binding is not None:
        defaults = json.loads(binding["default_values_json"] or "{}")
        overrides = json.loads(binding["override_values_json"] or "{}")
        effective = {**defaults, **overrides}
        template_name = binding["template_name"]

    offer_payloads = [dict(o) for o in offers]
    component_payloads: list[dict[str, Any]] = []
    for component in components:
        items = connection.execute(
            """
            SELECT item_name, item_kind, duration_label, item_value, description_text, terms_text, display_order
            FROM campaign_component_items
            WHERE component_id = ?
            ORDER BY display_order ASC, id ASC;
            """,
            (component["id"],),
        ).fetchall()
        component_payloads.append(
            {
                "component_key": component["component_key"],
                "component_kind": component["component_kind"],
                "display_title": component["display_title"],
                "subtitle": component["subtitle"],
                "description_text": component["description_text"],
                "display_order": component["display_order"],
                "items": [dict(item) for item in items],
            }
        )
    if not component_payloads:
        component_payloads = _fallback_components(offer_payloads)

    return {
        "campaign_id": campaign_id,
        "campaign_name": row["campaign_name"],
        "title": row["title"],
        "objective": row["objective"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "business_display_name": row["business_display_name"],
        "business_legal_name": row["business_legal_name"],
        "theme": dict(theme) if theme else {},
        "location": dict(location) if location else None,
        "contacts": [dict(c) for c in contacts],
        "offers": offer_payloads,
        "components": component_payloads,
        "effective_values": effective,
        "template_name": template_name,
    }


def _phone(contacts: list[dict[str, Any]]) -> str | None:
    for c in contacts:
        if c["contact_type"] == "phone":
            return c["contact_value"]
    return None


def _website(contacts: list[dict[str, Any]]) -> str | None:
    for c in contacts:
        if c["contact_type"] == "website":
            return c["contact_value"]
    return None


class _FlyerPDF(FPDF):
    def __init__(self, ctx: dict[str, Any]) -> None:
        super().__init__(orientation="portrait", unit="mm", format="letter")
        self.ctx = ctx
        self.set_margins(_MARGIN, _MARGIN, _MARGIN)
        self.set_auto_page_break(auto=True, margin=_MARGIN)
        self.add_page()

    def _primary_rgb(self) -> tuple[int, int, int]:
        return _hex_to_rgb(self.ctx["theme"].get("primary_color"), _DEFAULT_PRIMARY)

    def _accent_rgb(self) -> tuple[int, int, int]:
        return _hex_to_rgb(self.ctx["theme"].get("accent_color"), _DEFAULT_ACCENT)

    def _ink_rgb(self) -> tuple[int, int, int]:
        return _hex_to_rgb(_DEFAULT_INK, _DEFAULT_INK)

    def _draw_header_bar(self) -> None:
        r, g, b = self._primary_rgb()
        self.set_fill_color(r, g, b)
        self.rect(0, 0, _PAGE_W, 18, style="F")
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 12)
        biz = self.ctx["business_display_name"]
        self.set_xy(_MARGIN, 5)
        self.cell(_CONTENT_W, 8, biz, align="C")

    def _draw_headline(self) -> None:
        headline = self.ctx["effective_values"].get("headline") or self.ctx["title"]
        r, g, b = self._ink_rgb()
        self.set_text_color(r, g, b)
        self.set_font("Helvetica", "B", 22)
        self.set_y(24)
        self.multi_cell(_CONTENT_W, 10, headline, align="C")
        self.ln(2)

    def _draw_dates(self) -> None:
        start = self.ctx.get("start_date")
        end = self.ctx.get("end_date")
        if not start and not end:
            return
        r, g, b = _hex_to_rgb(self.ctx["theme"].get("secondary_color"), "#753991")
        self.set_text_color(r, g, b)
        self.set_font("Helvetica", "I", 11)
        date_str = ""
        if start and end:
                date_str = f"{start} - {end}"
        elif start:
            date_str = f"Starting {start}"
        self.cell(_CONTENT_W, 6, date_str, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def _draw_divider(self) -> None:
        r, g, b = self._accent_rgb()
        self.set_draw_color(r, g, b)
        self.set_line_width(0.8)
        x = _MARGIN
        y = self.get_y()
        self.line(x, y, x + _CONTENT_W, y)
        self.ln(4)

    def _draw_components(self) -> None:
        components = self.ctx.get("components") or _fallback_components(self.ctx.get("offers") or [])
        if not components:
            return
        r, g, b = self._ink_rgb()
        for component in components:
            self.set_text_color(r, g, b)
            self.set_font("Helvetica", "B", 13)
            self.cell(_CONTENT_W, 7, component.get("display_title") or "Offer Details", align="L", new_x="LMARGIN", new_y="NEXT")
            subtitle = component.get("subtitle")
            description_text = component.get("description_text")
            if subtitle:
                sr, sg, sb = _hex_to_rgb(self.ctx["theme"].get("secondary_color"), "#753991")
                self.set_text_color(sr, sg, sb)
                self.set_font("Helvetica", "I", 10)
                self.multi_cell(_CONTENT_W, 5, subtitle, align="L")
            if description_text:
                self.set_text_color(100, 100, 100)
                self.set_font("Helvetica", "", 9)
                self.multi_cell(_CONTENT_W, 5, description_text, align="L")
            self.ln(1)
            for item in component.get("items", []):
                name = item.get("item_name") or ""
                duration_label = item.get("duration_label") or ""
                value = item.get("item_value") or ""
                self.set_font("Helvetica", "B", 11)
                self.set_text_color(r, g, b)
                name_parts = [part for part in [name, duration_label] if part]
                label = " ".join(name_parts)
                content = f"{label}: {value}" if label and value else label or value
                self.multi_cell(_CONTENT_W, 6, content, align="L")
                if item.get("description_text"):
                    self.set_font("Helvetica", "", 8)
                    self.set_text_color(100, 100, 100)
                    self.multi_cell(_CONTENT_W, 4, item["description_text"], align="L")
                if item.get("start_date") and item.get("end_date"):
                    self.set_font("Helvetica", "I", 9)
                    ar, ag, ab = _hex_to_rgb(self.ctx["theme"].get("secondary_color"), "#753991")
                    self.set_text_color(ar, ag, ab)
                    self.cell(
                        _CONTENT_W,
                        5,
                        f"Valid {item['start_date']}-{item['end_date']}",
                        align="L",
                        new_x="LMARGIN",
                        new_y="NEXT",
                    )
                if item.get("terms_text"):
                    self.set_font("Helvetica", "I", 8)
                    self.set_text_color(100, 100, 100)
                    self.multi_cell(_CONTENT_W, 4, item["terms_text"], align="L")
                self.ln(2)

    def _draw_cta(self) -> None:
        cta = self.ctx["effective_values"].get("cta")
        if not cta:
            return
        self.ln(2)
        r, g, b = self._accent_rgb()
        self.set_fill_color(r, g, b)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 13)
        self.cell(_CONTENT_W, 12, cta, align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(4)

    def _draw_footer(self) -> None:
        loc = self.ctx.get("location")
        phone = _phone(self.ctx["contacts"])
        website = _website(self.ctx["contacts"])
        lines: list[str] = []
        if loc:
            addr_parts = [loc["line1"]]
            if loc.get("line2"):
                addr_parts.append(loc["line2"])
            addr_parts.append(f"{loc['city']}, {loc['state']} {loc['postal_code']}")
            lines.append("  ·  ".join(addr_parts))
        if phone:
            lines.append(f"Phone: {phone}")
        if website:
            lines.append(website)
        if not lines:
            return

        r, g, b = self._primary_rgb()
        self.set_fill_color(r, g, b)
        footer_h = 8 + len(lines) * 5
        footer_y = _PAGE_H - _MARGIN - footer_h
        self.set_y(footer_y)
        self._draw_divider()
        self.set_text_color(80, 80, 80)
        self.set_font("Helvetica", "", 9)
        for line in lines:
            self.cell(_CONTENT_W, 5, line, align="C", new_x="LMARGIN", new_y="NEXT")


def render_flyer(ctx: dict[str, Any]) -> bytes:
    pdf = _FlyerPDF(ctx)
    pdf._draw_header_bar()
    pdf._draw_headline()
    pdf._draw_dates()
    pdf._draw_divider()
    pdf._draw_components()
    pdf._draw_cta()
    pdf._draw_footer()
    return bytes(pdf.output())


def _file_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_campaign_artifact(
    connection: sqlite3.Connection,
    campaign_id: int,
    output_dir: Path,
    artifact_type: str = "flyer",
) -> dict[str, Any]:
    ctx = _collect_render_context(connection, campaign_id)

    if artifact_type not in {"flyer", "poster"}:
        raise ValueError(f"Unsupported artifact_type '{artifact_type}'")

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = ctx["campaign_name"].replace(" ", "-").lower()
    filename = f"{safe_name}-{artifact_type}.pdf"
    file_path = output_dir / filename

    pdf_bytes = render_flyer(ctx)
    checksum = _file_checksum(pdf_bytes)
    file_path.write_bytes(pdf_bytes)

    template_snapshot = json.dumps(
        {
            "template_name": ctx["template_name"],
            "effective_values": ctx["effective_values"],
        }
    )

    cursor = connection.execute(
        """
        INSERT INTO generated_artifacts
          (campaign_id, artifact_type, file_path, checksum, status, template_snapshot_json)
        VALUES (?, ?, ?, ?, 'complete', ?);
        """,
        (campaign_id, artifact_type, str(file_path), checksum, template_snapshot),
    )
    artifact_id = int(cursor.lastrowid)

    return {
        "id": artifact_id,
        "campaign_id": campaign_id,
        "artifact_type": artifact_type,
        "file_path": str(file_path),
        "checksum": checksum,
        "status": "complete",
    }
