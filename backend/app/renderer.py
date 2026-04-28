from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import deque
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas

try:
    from PIL import Image as _PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Page geometry (points, letter)
# ---------------------------------------------------------------------------
_PW, _PH = letter  # 612, 792
_MARGIN = 36.0

# Rich layout constants — mirrors reference coordinate scheme
_HEADER_H: float = 112.0
_HEADER_Y: float = _PH - 156.0          # 636
_SECTION_GAP: float = 14.0
_FEATURED_H: float = 230.0
_FEATURED_Y: float = _HEADER_Y - _SECTION_GAP - _FEATURED_H  # 392
_WEEKDAY_Y: float = 76.0
_WEEKDAY_TOP: float = _FEATURED_Y - _SECTION_GAP             # 378
_WEEKDAY_H: float = _WEEKDAY_TOP - _WEEKDAY_Y                # 302
_LEGAL_Y: float = 34.0
_LEGAL_H: float = 22.0

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

_COLOR_CREAM = colors.HexColor("#FBF7F4")
_COLOR_INK = colors.HexColor("#181818")
_COLOR_WHITE = colors.white


def _hex(val: str | None, fallback: str = "#000000") -> colors.HexColor:
    raw = (val or fallback).strip()
    if not raw.startswith("#"):
        raw = "#" + raw
    return colors.HexColor(raw)


def _palette(ctx: dict[str, Any]) -> dict[str, Any]:
    theme = ctx.get("theme", {})
    ev = ctx.get("effective_values", {})
    primary = _hex(theme.get("primary_color"), "#209dd7")
    secondary = _hex(theme.get("secondary_color"), "#753991")
    accent = _hex(ev.get("accent") or theme.get("accent_color"), "#ecad0a")
    cream = _hex(ev.get("color_bg"), "#FBF7F4")
    blush = _hex(ev.get("color_blush"), "#E8D5F0")
    card_1_bg = _hex(ev.get("color_card_1_bg"), "#F0E0FF")
    primary_light = _hex(ev.get("color_primary_light"), "#D5C8E8")
    return {
        "primary": primary,
        "secondary": secondary,
        "accent": accent,
        "cream": cream,
        "blush": blush,
        "card_1_bg": card_1_bg,
        "primary_light": primary_light,
        "ink": _COLOR_INK,
        "white": _COLOR_WHITE,
    }


# ---------------------------------------------------------------------------
# Logo loading (PIL-based BG removal identical to reference implementation)
# ---------------------------------------------------------------------------

def _load_logo(logo_path: Path | None) -> ImageReader | None:
    if logo_path is None or not logo_path.exists() or not _PIL_AVAILABLE:
        return None
    try:
        with _PILImage.open(logo_path).convert("RGB") as img:
            w, h = img.size
            cleaned = img.crop((0, 62, w, h)).convert("RGBA")
            pixels = cleaned.load()
            cw, ch = cleaned.size

            def near_white(r: int, g: int, b: int) -> bool:
                return r > 215 and g > 215 and b > 215

            q: deque = deque([(0, 0), (cw - 1, 0), (0, ch - 1), (cw - 1, ch - 1)])
            visited: set = set(q)
            while q:
                x, y = q.popleft()
                r, g, b, a = pixels[x, y]
                if a == 0 or not near_white(r, g, b):
                    continue
                pixels[x, y] = (r, g, b, 0)
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < cw and 0 <= ny < ch and (nx, ny) not in visited:
                        visited.add((nx, ny))
                        q.append((nx, ny))

            bbox = cleaned.getchannel("A").getbbox()
            if bbox:
                cleaned = cleaned.crop(bbox)

            buf = BytesIO()
            cleaned.save(buf, format="PNG")
            buf.seek(0)
            return ImageReader(buf)
    except Exception:
        return None


def _resolve_logo(theme: dict, data_dir: Path | None, business_display_name: str) -> Path | None:
    logo_str = (theme.get("logo_path") or "").strip()
    if not logo_str:
        return None
    logo_path = Path(logo_str)
    if logo_path.is_absolute():
        return logo_path if logo_path.exists() else None
    if data_dir is not None:
        biz_dir = data_dir / business_display_name.lower()
        candidate = biz_dir / logo_str
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Low-level drawing primitives (reportlab)
# ---------------------------------------------------------------------------

def _draw_centered(pdf: Any, text: str | None, x: float, y: float,
                   font: str, size: float, color: Any) -> None:
    pdf.setFillColor(color)
    pdf.setFont(font, size)
    pdf.drawCentredString(x, y, text or "")


def _draw_wrapped_centered(pdf: Any, text: str | None, cx: float, top_y: float,
                            max_w: float, font: str, size: float,
                            leading: float, color: Any) -> float:
    pdf.setFont(font, size)
    pdf.setFillColor(color)
    words = (text or "").split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        if stringWidth(candidate, font, size) <= max_w or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    y = top_y
    for line in lines:
        pdf.drawCentredString(cx, y, line)
        y -= leading
    return y


def _draw_rounded_panel(pdf: Any, x: float, y: float, w: float, h: float,
                         fill: Any, stroke: Any = None, radius: float = 18,
                         stroke_w: float = 1.0) -> None:
    pdf.setFillColor(fill)
    if stroke:
        pdf.setStrokeColor(stroke)
        pdf.setLineWidth(stroke_w)
    else:
        pdf.setStrokeColor(fill)
    pdf.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def _draw_offer_card(pdf: Any, x: float, y: float, w: float, h: float,
                      title: str, duration: str, price: str,
                      fill: Any, accent: Any, text_color: Any) -> None:
    _draw_rounded_panel(pdf, x, y, w, h, fill, accent, radius=16, stroke_w=2)
    pdf.setFillColor(accent)
    pdf.roundRect(x + 10, y + h - 36, w - 20, 24, 10, fill=1, stroke=0)
    _draw_centered(pdf, title, x + w / 2, y + h - 28, "Helvetica-Bold", 14, _COLOR_WHITE)
    _draw_centered(pdf, duration, x + w / 2, y + h - 58, "Helvetica", 11, text_color)
    _draw_centered(pdf, price, x + w / 2, y + 30, "Helvetica-Bold", 28, accent)


def _draw_weekday_strip(pdf: Any, x: float, y: float, w: float,
                         title: str, detail: str, price: str,
                         palette: dict) -> None:
    _draw_rounded_panel(pdf, x, y, w, 26, palette["primary_light"], palette["secondary"],
                        radius=10, stroke_w=1)
    pdf.setFillColor(palette["ink"])
    pdf.setFont("Helvetica-Bold", 10.5)
    pdf.drawString(x + 16, y + 8, title)
    pdf.setFont("Helvetica", 9.5)
    pdf.drawString(x + 180, y + 8, detail)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawRightString(x + w - 16, y + 7, price)


# ---------------------------------------------------------------------------
# Rich branded layout (featured-offers + weekday-specials)
# ---------------------------------------------------------------------------

def _draw_rich_flyer(pdf: Any, ctx: dict, palette: dict, logo_reader: Any,
                      featured: list, weekday: list,
                      discount: list, legal: list) -> None:
    ev = ctx.get("effective_values", {})
    w = _PW
    h = _PH

    # Background
    pdf.setFillColor(palette["cream"])
    pdf.rect(0, 0, w, h, fill=1, stroke=0)

    # ----- Header panel -----
    hx = _MARGIN
    panel_w = w - _MARGIN * 2
    _draw_rounded_panel(pdf, hx, _HEADER_Y, panel_w, _HEADER_H,
                        palette["primary"], palette["primary"], radius=24, stroke_w=2)

    if logo_reader is not None:
        logo_w, logo_h = 58, 58
        logo_x = (w - logo_w) / 2
        logo_y = _HEADER_Y + _HEADER_H - logo_h - 6
        pdf.drawImage(logo_reader, logo_x, logo_y,
                      width=logo_w, height=logo_h, preserveAspectRatio=True)

    biz_name = ev.get("business_name") or ctx.get("business_display_name", "")
    biz_sub = ev.get("business_subtitle") or ctx.get("business_legal_name", "")
    _draw_centered(pdf, biz_name.upper(), w / 2, _HEADER_Y + 28,
                   "Helvetica-Bold", 22, palette["white"])
    _draw_centered(pdf, biz_sub, w / 2, _HEADER_Y + 8,
                   "Times-Italic", 16, palette["primary_light"])

    component_footnotes: list[str] = []

    def title_with_marker(component: dict[str, Any] | None) -> str:
        if component is None:
            return ""
        title = component.get("display_title") or ""
        footnote = (component.get("footnote_text") or "").strip()
        if footnote:
            component_footnotes.append(footnote)
            return f"{title} **"
        return title

    # ----- Featured offers panel (Mother's Day / similar) -----
    if featured:
        comp = featured[0]
        _draw_rounded_panel(pdf, hx, _FEATURED_Y, panel_w, _FEATURED_H,
                            palette["blush"], palette["accent"], radius=24, stroke_w=2)
        _draw_centered(pdf, title_with_marker(comp), w / 2,
                       _FEATURED_Y + _FEATURED_H - 34, "Helvetica-Bold", 23, palette["primary"])
        subtitle = comp.get("subtitle") or ""
        if subtitle:
            _draw_wrapped_centered(pdf, subtitle, w / 2, _FEATURED_Y + _FEATURED_H - 62,
                                   w - 140, "Times-Italic", 14, 17, _COLOR_INK)

        items = comp.get("items", [])
        card_y = _FEATURED_Y + 42
        card_h = 112.0
        card_w = (panel_w - 28) / 2

        if len(items) >= 2:
            draw_cards = items[:2]
            # Card 1
            i0 = draw_cards[0]
            _draw_offer_card(pdf, hx + 14, card_y, card_w, card_h,
                             i0.get("item_name") or "", i0.get("duration_label") or "",
                             i0.get("item_value") or "",
                             palette["card_1_bg"], palette["accent"], _COLOR_INK)
            # Card 2
            i1 = draw_cards[1]
            _draw_offer_card(pdf, hx + 14 + card_w + 14, card_y, card_w, card_h,
                             i1.get("item_name") or "", i1.get("duration_label") or "",
                             i1.get("item_value") or "",
                             palette["white"], palette["primary"], _COLOR_INK)
        elif len(items) == 1:
            i0 = items[0]
            _draw_offer_card(pdf, hx + 14, card_y, panel_w - 28, card_h,
                             i0.get("item_name") or "", i0.get("duration_label") or "",
                             i0.get("item_value") or "",
                             palette["card_1_bg"], palette["accent"], _COLOR_INK)

    # ----- Weekday specials panel -----
    _draw_rounded_panel(pdf, hx, _WEEKDAY_Y, panel_w, _WEEKDAY_H,
                        palette["primary"], palette["primary"], radius=24, stroke_w=2)

    if weekday:
        wd_comp = weekday[0]
        _draw_centered(pdf, title_with_marker(wd_comp), w / 2,
                       _WEEKDAY_Y + _WEEKDAY_H - 34, "Helvetica-Bold", 22, palette["white"])
        wd_sub = wd_comp.get("subtitle") or ""
        if wd_sub:
            _draw_centered(pdf, wd_sub, w / 2, _WEEKDAY_Y + _WEEKDAY_H - 56,
                           "Times-Italic", 14, palette["primary_light"])

        strips_x = hx + 18
        strips_w = w - (hx + 18) * 2
        wd_items = wd_comp.get("items", [])
        # Preserve source order top-to-bottom to match the reference layout.
        strip_top = _WEEKDAY_Y + 172
        for idx, item in enumerate(wd_items):
            sy = strip_top - (idx * 34)
            _draw_weekday_strip(pdf, strips_x, sy, strips_w,
                                item.get("item_name") or "",
                                item.get("duration_label", ""),
                                item.get("item_value", ""),
                                palette)

    # ----- Discount strip (services panel) -----
    if discount:
        ds_comp = discount[0]
        ds_items = ds_comp.get("items", [])
        services_panel_y = _WEEKDAY_Y + 34
        services_panel_h = 62.0
        panel_inner_w = panel_w - 32

        _draw_rounded_panel(pdf, hx + 16, services_panel_y, panel_inner_w, services_panel_h,
                            palette["white"], palette["secondary"], radius=18, stroke_w=2)

        if ds_items:
            # Item 1 → inside panel
            it0 = ds_items[0]
            _draw_centered(pdf, it0.get("item_name") or "", w / 2,
                           services_panel_y + services_panel_h - 18,
                           "Helvetica-Bold", 17, palette["primary"])
            services_desc = it0.get("description_text") or ""
            if services_desc:
                _draw_wrapped_centered(pdf, services_desc, w / 2,
                                       services_panel_y + 24, w - 160,
                                       "Helvetica", 10, 12, _COLOR_INK)

            # Item 2+ → below panel as italic text
            if len(ds_items) > 1:
                it1 = ds_items[1]
                _draw_centered(pdf, it1.get("item_name") or "", w / 2,
                               services_panel_y - 16,
                               "Times-Italic", 14, palette["accent"])

    # ----- Footer contact line (inside weekday panel, very bottom) -----
    footer_text = ev.get("footer") or ""
    if footer_text:
        _draw_centered(pdf, footer_text, w / 2, _WEEKDAY_Y + 6,
                       "Helvetica-Bold", 10, palette["white"])

    # ----- Legal strip (below weekday panel) -----
    legal_inner_w = panel_w - 40
    _draw_rounded_panel(pdf, hx + 20, _LEGAL_Y, legal_inner_w, _LEGAL_H,
                        palette["primary_light"], palette["secondary"], radius=10, stroke_w=1)

    legal_text = ""
    if legal:
        legal_text = legal[0].get("description_text") or ""
    if not legal_text:
        legal_text = ev.get("legal") or ""
    if legal_text:
        _draw_centered(pdf, legal_text, w / 2, _LEGAL_Y + 7,
                       "Helvetica-Bold", 10, _COLOR_INK)

    campaign_footnote = (ctx.get("campaign_footnote_text") or "").strip()
    footer_notes = [f"** {note}" for note in component_footnotes]
    if campaign_footnote:
        footer_notes.append(f"** {campaign_footnote}")
    if footer_notes:
        note_y = 18.0
        for note in footer_notes[:2]:
            _draw_wrapped_centered(pdf, note, w / 2, note_y, w - 80, "Helvetica", 8.5, 9.5, _COLOR_INK)
            note_y -= 10.0


# ---------------------------------------------------------------------------
# Simple fallback layout (generic campaigns without rich component kinds)
# ---------------------------------------------------------------------------

def _draw_simple_flyer(pdf: Any, ctx: dict, palette: dict) -> None:
    ev = ctx.get("effective_values", {})
    w = _PW
    h = _PH

    # Background
    pdf.setFillColor(palette["cream"])
    pdf.rect(0, 0, w, h, fill=1, stroke=0)

    # Header bar
    pdf.setFillColor(palette["primary"])
    pdf.rect(0, h - 48, w, 48, fill=1, stroke=0)
    biz_name = ev.get("business_name") or ctx.get("business_display_name", "")
    _draw_centered(pdf, biz_name.upper(), w / 2, h - 22,
                   "Helvetica-Bold", 18, palette["white"])
    biz_sub = ev.get("business_subtitle") or ctx.get("business_legal_name", "")
    if biz_sub:
        _draw_centered(pdf, biz_sub, w / 2, h - 38,
                       "Times-Italic", 12, palette["primary_light"])

    # Headline
    headline = ev.get("headline") or ctx.get("title") or ""
    pdf.setFillColor(palette["primary"])
    pdf.roundRect(_MARGIN, h - 102, w - _MARGIN * 2, 40, 12, fill=1, stroke=0)
    _draw_centered(pdf, headline, w / 2, h - 76, "Helvetica-Bold", 20, palette["white"])

    # Components
    y = h - 130
    for comp in ctx.get("components", []):
        if y < 120:
            break
        # Section title
        pdf.setFillColor(palette["accent"])
        pdf.roundRect(_MARGIN, y - 6, w - _MARGIN * 2, 22, 8, fill=1, stroke=0)
        title = (comp.get("display_title") or "").upper()
        if (comp.get("footnote_text") or "").strip():
            title = f"{title} **"
        _draw_centered(pdf, title, w / 2, y + 8,
                       "Helvetica-Bold", 12, palette["white"])
        y -= 36

        for item in comp.get("items", []):
            if y < 100:
                break
            parts = [p for p in [item.get("item_name"), item.get("duration_label")] if p]
            label = " – ".join(parts)
            value = item.get("item_value") or ""
            row = f"{label}: {value}" if label and value else label or value
            pdf.setFillColor(palette["ink"])
            pdf.setFont("Helvetica", 11)
            pdf.drawCentredString(w / 2, y, row)
            y -= 18

        y -= 10

    # CTA bar
    cta = ev.get("cta") or ""
    if cta and y > 80:
        pdf.setFillColor(palette["accent"])
        pdf.roundRect(_MARGIN, y - 6, w - _MARGIN * 2, 22, 8, fill=1, stroke=0)
        _draw_centered(pdf, cta, w / 2, y + 8, "Helvetica-Bold", 12, palette["white"])
        y -= 36

    # Footer
    footer = ev.get("footer") or ""
    if footer:
        _draw_centered(pdf, footer, w / 2, 40, "Helvetica", 9, palette["secondary"])

    component_notes = [
        f"** {(comp.get('footnote_text') or '').strip()}"
        for comp in ctx.get("components", [])
        if (comp.get("footnote_text") or "").strip()
    ]
    campaign_note = (ctx.get("campaign_footnote_text") or "").strip()
    if campaign_note:
        component_notes.append(f"** {campaign_note}")
    if component_notes:
        _draw_wrapped_centered(pdf, "   ".join(component_notes[:2]), w / 2, 24, w - 100,
                               "Helvetica", 8.5, 10, palette["ink"])


# ---------------------------------------------------------------------------
# Context collector (unchanged from previous implementation)
# ---------------------------------------------------------------------------

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
        SELECT c.id, c.campaign_name, c.campaign_key, c.title, c.objective, c.footnote_text,
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
        SELECT id, component_key, component_kind, display_title, footnote_text, subtitle, description_text, display_order
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
                "footnote_text": component["footnote_text"],
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
        "campaign_footnote_text": row["footnote_text"],
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


# ---------------------------------------------------------------------------
# Public render API
# ---------------------------------------------------------------------------

def render_flyer(ctx: dict[str, Any], data_dir: Path | None = None) -> bytes:
    palette = _palette(ctx)
    components = ctx.get("components", [])

    featured = [c for c in components if c.get("component_kind") == "featured-offers"]
    weekday = [c for c in components if c.get("component_kind") == "weekday-specials"]
    discount = [c for c in components if c.get("component_kind") == "discount-strip"]
    legal = [c for c in components if c.get("component_kind") == "legal-note"]
    use_rich = bool(featured or weekday)

    # Resolve logo
    logo_reader = None
    if use_rich:
        logo_path = _resolve_logo(
            ctx.get("theme", {}),
            data_dir,
            ctx.get("business_display_name", ""),
        )
        logo_reader = _load_logo(logo_path)

    buf = BytesIO()
    pdf = rl_canvas.Canvas(buf, pagesize=letter)
    pdf.setTitle(ctx.get("title") or "Flyer")

    if use_rich:
        _draw_rich_flyer(pdf, ctx, palette, logo_reader, featured, weekday, discount, legal)
    else:
        _draw_simple_flyer(pdf, ctx, palette)

    pdf.showPage()
    pdf.save()
    return buf.getvalue()


def _file_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_campaign_artifact(
    connection: sqlite3.Connection,
    campaign_id: int,
    output_dir: Path,
    artifact_type: str = "flyer",
    data_dir: Path | None = None,
) -> dict[str, Any]:
    ctx = _collect_render_context(connection, campaign_id)

    if artifact_type not in {"flyer", "poster"}:
        raise ValueError(f"Unsupported artifact_type '{artifact_type}'")

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = ctx["campaign_name"].replace(" ", "-").lower()
    filename = f"{safe_name}-{artifact_type}.pdf"
    file_path = output_dir / filename

    pdf_bytes = render_flyer(ctx, data_dir=data_dir)
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
