from __future__ import annotations

import hashlib
import json
import math
import re
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
from sqlalchemy.orm import Session

from .models import Campaign, CampaignTemplateBinding, GeneratedArtifact

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

_DEFAULT_RENDER_LAYOUT: dict[str, Any] = {
    "page": {"size": "letter", "width": _PW, "height": _PH, "margin": _MARGIN},
    "regions": {
        "header": {"x": _MARGIN, "y": _HEADER_Y, "w": _PW - _MARGIN * 2, "h": _HEADER_H},
        "featured": {"x": _MARGIN, "y": _FEATURED_Y, "w": _PW - _MARGIN * 2, "h": _FEATURED_H},
        "secondary": {"x": _MARGIN, "y": _WEEKDAY_Y, "w": _PW - _MARGIN * 2, "h": _WEEKDAY_H},
        "discount": {"x": _MARGIN + 16, "y": _WEEKDAY_Y + 34, "w": _PW - _MARGIN * 2 - 32, "h": 62.0},
        "legal": {"x": _MARGIN + 20, "y": _LEGAL_Y, "w": _PW - _MARGIN * 2 - 40, "h": _LEGAL_H},
        "campaign-footnote": {"x": 40.0, "y": 18.0, "w": _PW - 80.0, "h": 20.0},
    },
    "component_kind_defaults": {
        "featured-offers": {"render_region": "featured", "render_mode": "offer-card-grid"},
        "weekday-specials": {"render_region": "secondary", "render_mode": "strip-list"},
        "other-offers": {"render_region": "secondary", "render_mode": "strip-list"},
        "secondary-offers": {"render_region": "secondary", "render_mode": "strip-list"},
        "discount-strip": {"render_region": "discount", "render_mode": "discount-panel"},
        "legal-note": {"render_region": "legal", "render_mode": "legal-text"},
    },
    "typography": {
        "business_name": {"font": "Helvetica-Bold", "size": 22.0},
        "business_subtitle": {"font": "Times-Italic", "size": 16.0},
        "section_title": {"font": "Helvetica-Bold", "size": 21.0},
        "section_subtitle": {"font": "Times-Italic", "size": 12.0},
        "item_name": {"font": "Helvetica-Bold", "size": 11.0},
        "item_detail": {"font": "Helvetica", "size": 11.0},
        "item_value": {"font": "Helvetica-Bold", "size": 11.0},
        "footnote": {"font": "Helvetica", "size": 8.0},
    },
    "geometry": {
        "section_gap": 14.0,
        "panel_radius": 24.0,
        "card_radius": 12.0,
        "strip_radius": 10.0,
        "stroke_width": 2.0,
    },
    "styles": {
        "radius": {"panel": 24.0, "card": 12.0, "strip": 10.0},
        "featured": {
            "max_columns": 3,
            "card_gap": 8.0,
            "row_gap": 8.0,
            "max_card_width": 132.0,
            "min_card_height": 52.0,
            "max_card_height": 58.0,
            "item_top_offset": 74.0,
            "subtitle_top_offset": 62.0,
            "subtitle_font": "Helvetica-BoldOblique",
            "subtitle_size": 12.5,
            "subtitle_leading": 14.5,
            "subtitle_color": "#181818",
            "duration_font": "Helvetica-Bold",
            "duration_color": "#181818",
            "price_badge_fill": "#FFE66D",
            "price_badge_color": "#181818",
            "price_badge_padding_x": 9.0,
            "price_badge_height": 15.0,
            "footnote_offset": 12.0,
        },
        "secondary": {
            "strip_height": 26.0,
            "strip_gap": 8.0,
            "strip_top_offset": 92.0,
            "bottom_offset": 20.0,
            "discount_clearance": 10.0,
            "subtitle_font": "Helvetica-BoldOblique",
            "subtitle_size": 14.0,
            "duration_font": "Helvetica-Bold",
            "duration_color": "#181818",
        },
        "discount": {
            "description_font": "Helvetica",
            "description_size": 10.0,
            "description_leading": 12.0,
            "note_font": "Helvetica-BoldOblique",
            "note_size": 13.0,
            "note_color": "#FFFFFF",
        },
        "header": {
            "business_subtitle_font": "Helvetica-BoldOblique",
            "business_subtitle_size": 15.0,
            "business_subtitle_color": "#FFFFFF",
        },
        "footnotes": {"marker": "**", "max_campaign_notes": 2},
    },
}

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

_COLOR_CREAM = colors.HexColor("#FBF7F4")
_COLOR_INK = colors.HexColor("#181818")
_COLOR_WHITE = colors.white

# Custom color name mapping for natural language colors not in CSS/ReportLab
_CUSTOM_COLORS = {
    "light purple": "#c8a2c8",
    "lavender": "#e6d5ff",
}


def _hex(val: str | None, fallback: str = "#000000") -> colors.Color:
    raw = (val or "").strip()
    if raw:
        # Check custom color names first (with normalization)
        raw_normalized = raw.lower().replace(" ", "").replace("-", "").replace("_", "")
        for custom_name, hex_val in _CUSTOM_COLORS.items():
            if raw_normalized == custom_name.lower().replace(" ", "").replace("-", "").replace("_", ""):
                try:
                    return colors.HexColor(hex_val)
                except (ValueError, TypeError):
                    pass
        
        # Try standard CSS color names with various normalizations
        candidates = [raw, raw.lower().replace(" ", ""), raw.lower().replace("-", ""), raw.lower().replace("_", "")]
        for candidate in candidates:
            try:
                # Accept names like "lightgreen" and common natural variants like "light green".
                return colors.toColor(candidate)
            except (ValueError, TypeError):
                continue
        if not raw.startswith("#"):
            raw = "#" + raw
        try:
            return colors.HexColor(raw)
        except (ValueError, TypeError):
            pass

    try:
        return colors.toColor(fallback)
    except (ValueError, TypeError):
        return colors.HexColor("#000000")


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
    legal_bg = _hex(ev.get("color_legal_bg"), _string_hex(primary_light))
    legal_border = _hex(ev.get("color_legal_border"), _string_hex(secondary))
    return {
        "primary": primary,
        "secondary": secondary,
        "accent": accent,
        "cream": cream,
        "blush": blush,
        "card_1_bg": card_1_bg,
        "primary_light": primary_light,
        "legal_bg": legal_bg,
        "legal_border": legal_border,
        "ink": _COLOR_INK,
        "white": _COLOR_WHITE,
    }


def _string_hex(color_value: Any) -> str:
    # reportlab Color objects expose rgb() values in 0..1; convert to #RRGGBB.
    if hasattr(color_value, "rgb"):
        r, g, b = color_value.rgb()
        return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"
    return "#000000"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            merged[key] = _deep_merge(value, {})
        else:
            merged[key] = value
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _layout(ctx: dict[str, Any]) -> dict[str, Any]:
    template = ctx.get("template") or {}
    return _deep_merge(_DEFAULT_RENDER_LAYOUT, template.get("layout") or {})


def _region(layout: dict[str, Any], key: str) -> dict[str, float]:
    region = ((layout.get("regions") or {}).get(key) or {})
    return {
        "x": float(region.get("x", 0.0)),
        "y": float(region.get("y", 0.0)),
        "w": float(region.get("w", _PW)),
        "h": float(region.get("h", _PH)),
    }


def _style(layout: dict[str, Any], *path: str, fallback: Any = None) -> Any:
    current: Any = layout.get("styles") or {}
    for key in path:
        if not isinstance(current, dict):
            return fallback
        current = current.get(key)
    return fallback if current is None else current


def _component_render_defaults(layout: dict[str, Any], component: dict[str, Any]) -> dict[str, str | None]:
    defaults = (layout.get("component_kind_defaults") or {}).get(component.get("component_kind") or "", {})
    return {
        "render_region": component.get("render_region") or defaults.get("render_region"),
        "render_mode": component.get("render_mode") or defaults.get("render_mode"),
    }


def _components_by_region(ctx: dict[str, Any], layout: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for component in ctx.get("components", []):
        defaults = _component_render_defaults(layout, component)
        region = defaults.get("render_region") or "body"
        component.setdefault("render_region", region)
        component.setdefault("render_mode", defaults.get("render_mode"))
        grouped.setdefault(region, []).append(component)
    return grouped


def _region_components(
    grouped: dict[str, list[dict[str, Any]]],
    region: str,
    modes: set[str],
) -> list[dict[str, Any]]:
    return [
        component
        for component in grouped.get(region, [])
        if not modes or component.get("render_mode") in modes
    ]


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
                      fill: Any, accent: Any, text_color: Any,
                      title_color: Any = None, price_color: Any = None) -> None:
    _draw_rounded_panel(pdf, x, y, w, h, fill, accent, radius=16, stroke_w=2)
    pdf.setFillColor(accent)
    pdf.roundRect(x + 10, y + h - 36, w - 20, 24, 10, fill=1, stroke=0)
    _draw_centered(pdf, title, x + w / 2, y + h - 28, "Helvetica-Bold", 14, title_color or _COLOR_WHITE)
    _draw_centered(pdf, duration, x + w / 2, y + h - 58, "Helvetica", 11, text_color)
    _draw_centered(pdf, price, x + w / 2, y + 30, "Helvetica-Bold", 28, price_color or accent)


def _draw_compact_offer_card(pdf: Any, x: float, y: float, w: float, h: float,
                              title: str, duration: str, price: str,
                              fill: Any, accent: Any, text_color: Any,
                              title_color: Any = None, price_color: Any = None,
                              radius: float = 12.0,
                              duration_font: str = "Helvetica",
                              duration_color: Any = None,
                              price_badge_fill: Any = None,
                              price_badge_padding_x: float = 0.0,
                              price_badge_height: float = 0.0) -> None:
    """Compact card for featured offers - fits 3 per row with symmetrical spacing and standardized fonts."""
    _draw_rounded_panel(pdf, x, y, w, h, fill, accent, radius=radius, stroke_w=1.5)
    
    # Title bar (spans h-17 to h-4 relative to y)
    pdf.setFillColor(accent)
    pdf.roundRect(x + 6, y + h - 17, w - 12, 13, 6.5, fill=1, stroke=0)
    
    # Label positions are calculated to ensure vertical symmetry across all text elements.
    # Standardized 11pt typography across all fields for consistency.
    font_size = 11.0 if h >= 52 else 9.5
    
    # 1. Price sits at a consistent baseline
    price_y = y + 7
    # 2. Title is centered vertically within the title bar (baseline centered)
    title_y = y + h - 14.35
    
    # 3. Duration is centered in the whitespace between Price top and Title baseline
    price_top = price_y + (font_size * 0.7)
    available_gap = title_y - price_top
    duration_y = price_top + (available_gap / 2) - (font_size * 0.35)
    
    _draw_centered(pdf, title, x + w / 2, title_y, "Helvetica-Bold", font_size if h >= 52 else 10, title_color or _COLOR_WHITE)
    _draw_centered(pdf, duration, x + w / 2, duration_y, duration_font, font_size, duration_color or text_color)
    if price and price_badge_fill and price_badge_height > 0:
        badge_w = stringWidth(price, "Helvetica-Bold", font_size) + (price_badge_padding_x * 2)
        badge_x = x + (w - badge_w) / 2
        badge_y = price_y - 4
        _draw_rounded_panel(pdf, badge_x, badge_y, badge_w, price_badge_height, price_badge_fill, price_badge_fill, radius=price_badge_height / 2, stroke_w=0)
    _draw_centered(pdf, price, x + w / 2, price_y, "Helvetica-Bold", font_size, price_color or accent)


def _draw_weekday_strip(pdf: Any, x: float, y: float, w: float,
                         title: str, detail: str, price: str,
                         palette: dict, strip_fill: Any = None,
                         radius: float = 10.0,
                         typography: dict | None = None,
                         detail_font: str | None = None,
                         detail_color: Any = None) -> None:
    _draw_rounded_panel(pdf, x, y, w, 26, strip_fill or palette["primary_light"], palette["secondary"],
                        radius=radius, stroke_w=1)
    pdf.setFillColor(palette["ink"])
    
    # Use typography overrides if provided
    typo = typography or {}
    name_style = typo.get("item_name", {})
    detail_style = typo.get("item_detail", {})
    value_style = typo.get("item_value", {})
    
    pdf.setFont(name_style.get("font", "Helvetica-Bold"), name_style.get("size", 11.0))
    pdf.drawString(x + 16, y + 8, title)
    
    pdf.setFillColor(detail_color or palette["ink"])
    pdf.setFont(detail_font or detail_style.get("font", "Helvetica"), detail_style.get("size", 11.0))
    pdf.drawString(x + 180, y + 8, detail)
    
    pdf.setFillColor(palette["ink"])
    pdf.setFont(value_style.get("font", "Helvetica-Bold"), value_style.get("size", 11.0))
    pdf.drawRightString(x + w - 16, y + 8, price)


# ---------------------------------------------------------------------------
# Rich branded layout (featured-offers + weekday-specials)
# ---------------------------------------------------------------------------

def _draw_rich_flyer(pdf: Any, ctx: dict, palette: dict, logo_reader: Any,
                      featured: list, weekday: list,
                      discount: list, legal: list) -> None:
    ev = ctx.get("effective_values", {})
    layout = _layout(ctx)
    typography = layout.get("typography", {})
    geometry = layout.get("geometry", {})
    header_region = _region(layout, "header")
    featured_region = _region(layout, "featured")
    secondary_region = _region(layout, "secondary")
    discount_region = _region(layout, "discount")
    legal_region = _region(layout, "legal")
    footnote_region = _region(layout, "campaign-footnote")
    w = _PW
    h = _PH

    # Background
    pdf.setFillColor(palette["cream"])
    pdf.rect(0, 0, w, h, fill=1, stroke=0)

    # ----- Header panel -----
    hx = header_region["x"]
    panel_w = header_region["w"]
    panel_radius = geometry.get("panel_radius", 24.0)
    stroke_w = geometry.get("stroke_width", 2.0)
    _draw_rounded_panel(pdf, hx, header_region["y"], panel_w, header_region["h"],
                        palette["primary"], palette["primary"], radius=panel_radius, stroke_w=stroke_w)

    if logo_reader is not None:
        logo_w, logo_h = 58, 58
        logo_x = (w - logo_w) / 2
        logo_y = header_region["y"] + header_region["h"] - logo_h - 6
        pdf.drawImage(logo_reader, logo_x, logo_y,
                      width=logo_w, height=logo_h, preserveAspectRatio=True)

    biz_name = ev.get("business_name") or ctx.get("business_display_name", "")
    biz_sub = ev.get("business_subtitle") or ctx.get("business_legal_name", "")
    
    biz_name_style = typography.get("business_name", {})
    _draw_centered(pdf, biz_name.upper(), w / 2, header_region["y"] + 28,
                   biz_name_style.get("font", "Helvetica-Bold"), 
                   biz_name_style.get("size", 22.0), palette["white"])
    
    biz_sub_style = typography.get("business_subtitle", {})
    biz_sub_font = _style(layout, "header", "business_subtitle_font", fallback=None) or biz_sub_style.get("font", "Times-Italic")
    biz_sub_size = float(
        _style(layout, "header", "business_subtitle_size", fallback=None) or biz_sub_style.get("size", 16.0)
    )
    biz_sub_color = _hex(
        ev.get("business_subtitle_color") or _style(layout, "header", "business_subtitle_color", fallback=None),
        _string_hex(_COLOR_WHITE),
    )
    _draw_centered(pdf, biz_sub, w / 2, header_region["y"] + 8,
                   biz_sub_font,
                   biz_sub_size, biz_sub_color)

    def title_with_marker(component: dict[str, Any] | None) -> str:
        if component is None:
            return ""
        title = component.get("display_title") or ""
        footnote = (component.get("footnote_text") or "").strip()
        if footnote:
            return f"{title} **"
        return title

    # ----- Featured offers panel (Mother's Day / similar) -----
    if featured:
        comp = featured[0]
        items = comp.get("items", [])
        num_items = len(items)
        max_columns = int(_style(layout, "featured", "max_columns", fallback=3))
        cols_per_row = min(max_columns, max(1, num_items))
        num_rows = math.ceil(num_items / cols_per_row) if num_items > 0 else 1
        
        comp_style = comp.get("style") or {}
        featured_fill = _hex(comp.get("background_color"), _string_hex(palette["blush"]))
        featured_header_color = comp.get("header_accent_color")
        if not featured_header_color and items:
            featured_header_color = items[0].get("background_color")
        featured_header_accent = _hex(featured_header_color, _string_hex(palette["accent"]))
        panel_top = featured_region["y"]
        panel_h = featured_region["h"]
        _draw_rounded_panel(pdf, hx, panel_top, panel_w, panel_h,
                            featured_fill, palette["accent"], radius=panel_radius, stroke_w=stroke_w)
        
        section_title_style = typography.get("section_title", {})
        _draw_centered(pdf, title_with_marker(comp), w / 2,
                       panel_top + panel_h - 34, 
                       section_title_style.get("font", "Helvetica-Bold"), 
                       section_title_style.get("size", 21.0), palette["primary"])
        
        # Carve out a fixed inner content region for items between the subtitle and
        # the footnote so cards can never encroach on either boundary.
        subtitle = comp.get("subtitle") or ""
        items_top_boundary = panel_top + panel_h - float(_style(layout, "featured", "item_top_offset", fallback=74.0))
        if subtitle:
            section_subtitle_style = typography.get("section_subtitle", {})
            subtitle_font = (
                comp_style.get("subtitle_font")
                or _style(layout, "featured", "subtitle_font", fallback=None)
                or section_subtitle_style.get("font", "Times-Italic")
            )
            subtitle_size = float(
                comp_style.get("subtitle_size")
                or _style(layout, "featured", "subtitle_size", fallback=None)
                or section_subtitle_style.get("size", 12.0)
            )
            subtitle_leading = float(
                comp_style.get("subtitle_leading")
                or _style(layout, "featured", "subtitle_leading", fallback=14.0)
            )
            subtitle_color = _hex(
                comp_style.get("subtitle_color")
                or _style(layout, "featured", "subtitle_color", fallback=None),
                _string_hex(_COLOR_INK),
            )
            subtitle_bottom = _draw_wrapped_centered(
                pdf,
                subtitle,
                w / 2,
                panel_top + panel_h - float(_style(layout, "featured", "subtitle_top_offset", fallback=62.0)),
                w - 140,
                subtitle_font,
                subtitle_size,
                subtitle_leading,
                subtitle_color,
            )
            items_top_boundary = min(items_top_boundary, subtitle_bottom - 10.0)

        footnote_y = panel_top + float(_style(layout, "featured", "footnote_offset", fallback=12.0))
        items_bottom_boundary = footnote_y + 18.0
        row_spacing = float(_style(layout, "featured", "row_gap", fallback=8.0))
        available_h = max(48.0, items_top_boundary - items_bottom_boundary)
        min_card_h = float(_style(layout, "featured", "min_card_height", fallback=52.0))
        max_card_h = float(_style(layout, "featured", "max_card_height", fallback=58.0))
        card_h = max(min_card_h, min(max_card_h, (available_h - row_spacing * max(0, num_rows - 1)) / num_rows))

        # Keep the cards visually compact instead of stretching them to full width.
        card_gap = float(_style(layout, "featured", "card_gap", fallback=8.0))
        max_card_w = float(_style(layout, "featured", "max_card_width", fallback=132.0))
        available_w = panel_w - 40.0
        card_w = min(max_card_w, (available_w - card_gap * max(0, cols_per_row - 1)) / cols_per_row)
        grid_w = cols_per_row * card_w + card_gap * max(0, cols_per_row - 1)
        grid_x = hx + (panel_w - grid_w) / 2.0
        card_x_positions = [grid_x + idx * (card_w + card_gap) for idx in range(cols_per_row)]

        first_row_top = items_top_boundary
        card_y_start = first_row_top - card_h
        
        for row_idx in range(num_rows):
            card_y = card_y_start - (row_idx * (card_h + row_spacing))
            
            for col_idx in range(cols_per_row):
                item_idx = row_idx * cols_per_row + col_idx
                if item_idx < num_items:
                    item = items[item_idx]
                    item_style = item.get("style") or {}
                    # Priority: item-style -> component-style -> derived/default
                    item_title_color = _hex(item_style.get("title_color") or comp_style.get("item_title_color"), None)
                    item_price_color = _hex(item_style.get("price_color") or comp_style.get("item_price_color"), None)
                    price_badge_fill = _hex(
                        item_style.get("price_badge_fill")
                        or comp_style.get("price_badge_fill")
                        or _style(layout, "featured", "price_badge_fill", fallback=None),
                        "#FFE66D",
                    )
                    price_badge_padding_x = float(
                        item_style.get("price_badge_padding_x")
                        or comp_style.get("price_badge_padding_x")
                        or _style(layout, "featured", "price_badge_padding_x", fallback=9.0)
                    )
                    price_badge_height = float(
                        item_style.get("price_badge_height")
                        or comp_style.get("price_badge_height")
                        or _style(layout, "featured", "price_badge_height", fallback=15.0)
                    )
                    item_duration_font = (
                        item_style.get("duration_font")
                        or comp_style.get("item_duration_font")
                        or _style(layout, "featured", "duration_font", fallback="Helvetica")
                    )
                    item_duration_color = _hex(
                        item_style.get("duration_color")
                        or comp_style.get("item_duration_color")
                        or _style(layout, "featured", "duration_color", fallback=None),
                        _string_hex(_COLOR_INK),
                    )
                    
                    # Keep featured cards color-stable: item body can vary, but
                    # header accent stays consistent across all cards.
                    item_fill = _hex(item.get("background_color"), _string_hex(palette["card_1_bg"]))
                    item_accent = featured_header_accent
                    
                    # Resolve card radius from geometry or component style
                    card_radius = item_style.get("border_radius") or comp_style.get("border_radius") or geometry.get("card_radius", 12.0)
                    
                    _draw_compact_offer_card(pdf, card_x_positions[col_idx], card_y, card_w, card_h,
                                            item.get("item_name") or "", item.get("duration_label") or "",
                                            item.get("item_value") or "",
                                            item_fill, item_accent, _COLOR_INK,
                                            title_color=item_title_color, price_color=item_price_color,
                                            radius=card_radius,
                                            duration_font=item_duration_font,
                                            duration_color=item_duration_color,
                                            price_badge_fill=price_badge_fill,
                                            price_badge_padding_x=price_badge_padding_x,
                                            price_badge_height=price_badge_height)

        comp_note = (comp.get("footnote_text") or "").strip()
        if comp_note:
            footnote_style = typography.get("footnote", {})
            _draw_centered(pdf, f"** {comp_note}", w / 2, footnote_y,
                           footnote_style.get("font", "Helvetica"), 
                           footnote_style.get("size", 8.0), _COLOR_INK)

    # ----- Weekday specials panel -----
    secondary_text_color = palette["white"]
    if weekday:
        wd_comp = weekday[0]
        wd_comp_style = wd_comp.get("style") or {}
        weekday_fill = _hex(wd_comp.get("background_color"), _string_hex(palette["primary"]))
        wd_text_color = _hex(wd_comp.get("header_accent_color"), _string_hex(palette["white"]))
        secondary_text_color = wd_text_color
        _draw_rounded_panel(pdf, hx, secondary_region["y"], panel_w, secondary_region["h"],
                            weekday_fill, wd_text_color, radius=panel_radius, stroke_w=stroke_w)
        
        section_title_style = typography.get("section_title", {})
        _draw_centered(pdf, title_with_marker(wd_comp), w / 2,
                       secondary_region["y"] + secondary_region["h"] - 34, 
                       section_title_style.get("font", "Helvetica-Bold"), 
                       section_title_style.get("size", 22.0), wd_text_color)
        
        wd_sub = wd_comp.get("subtitle") or ""
        if wd_sub:
            section_subtitle_style = typography.get("section_subtitle", {})
            wd_subtitle_font = (
                wd_comp_style.get("subtitle_font")
                or _style(layout, "secondary", "subtitle_font", fallback=None)
                or section_subtitle_style.get("font", "Times-Italic")
            )
            wd_subtitle_size = float(
                wd_comp_style.get("subtitle_size")
                or _style(layout, "secondary", "subtitle_size", fallback=None)
                or section_subtitle_style.get("size", 14.0)
            )
            wd_subtitle_color = _hex(
                wd_comp_style.get("subtitle_color")
                or _style(layout, "secondary", "subtitle_color", fallback=None),
                _string_hex(wd_text_color),
            )
            _draw_centered(pdf, wd_sub, w / 2, secondary_region["y"] + secondary_region["h"] - 56,
                           wd_subtitle_font,
                           wd_subtitle_size, wd_subtitle_color)

        strips_x = hx + 18
        strips_w = w - (hx + 18) * 2
        wd_items = wd_comp.get("items", [])
        strip_h = float(_style(layout, "secondary", "strip_height", fallback=26.0))
        strip_gap = float(_style(layout, "secondary", "strip_gap", fallback=8.0))
        services_panel_y = discount_region["y"]
        services_panel_h = discount_region["h"]
        has_discount_panel = bool(discount)

        # Carve out weekday item bounds so strips never collide with header/subtitle
        # or the lower discount/footer region.
        # Keep a little breathing room below the subtitle before the first item strip.
        strips_top = secondary_region["y"] + secondary_region["h"] - float(_style(layout, "secondary", "strip_top_offset", fallback=92.0))
        if has_discount_panel:
            strips_bottom = services_panel_y + services_panel_h + float(_style(layout, "secondary", "discount_clearance", fallback=10.0))
        else:
            strips_bottom = secondary_region["y"] + float(_style(layout, "secondary", "bottom_offset", fallback=20.0))

        available_h = max(0.0, strips_top - strips_bottom)
        max_rows = int((available_h + strip_gap) // (strip_h + strip_gap))

        # Preserve source order top-to-bottom and render only what fits.
        strip_radius = wd_comp_style.get("border_radius") or geometry.get("strip_radius", 10.0)
        for idx, item in enumerate(wd_items[:max_rows]):
            sy = strips_top - (idx * (strip_h + strip_gap))
            item_style = item.get("style") or {}
            strip_fill = _hex(item.get("background_color"), _string_hex(palette["primary_light"]))
            detail_font = (
                item_style.get("duration_font")
                or wd_comp_style.get("item_duration_font")
                or _style(layout, "secondary", "duration_font", fallback="Helvetica")
            )
            detail_color = _hex(
                item_style.get("duration_color")
                or wd_comp_style.get("item_duration_color")
                or _style(layout, "secondary", "duration_color", fallback=None),
                _string_hex(_COLOR_INK),
            )
            _draw_weekday_strip(pdf, strips_x, sy, strips_w,
                                item.get("item_name") or "",
                                item.get("duration_label", ""),
                                item.get("item_value", ""),
                                palette,
                                strip_fill=strip_fill,
                                radius=item_style.get("border_radius") or strip_radius,
                                typography=typography,
                                detail_font=detail_font,
                                detail_color=detail_color)

        wd_note = (wd_comp.get("footnote_text") or "").strip()
        if wd_note:
            footnote_style = typography.get("footnote", {})
            _draw_centered(pdf, f"** {wd_note}", w / 2, secondary_region["y"] + 12,
                           footnote_style.get("font", "Helvetica"), 
                           footnote_style.get("size", 8.0), wd_text_color)

    # ----- Discount strip (services panel) -----
    if discount:
        ds_comp = discount[0]
        ds_comp_style = ds_comp.get("style") or {}
        ds_items = ds_comp.get("items", [])
        services_panel_y = discount_region["y"]
        services_panel_h = discount_region["h"]
        panel_inner_w = discount_region["w"]

        _draw_rounded_panel(pdf, discount_region["x"], services_panel_y, panel_inner_w, services_panel_h,
                            palette["white"], palette["secondary"], radius=18, stroke_w=2)

        if ds_items:
            # Item 1 → inside panel
            it0 = ds_items[0]
            _draw_centered(pdf, it0.get("item_name") or "", w / 2,
                           services_panel_y + services_panel_h - 18,
                           "Helvetica-Bold", 17, palette["primary"])
            services_desc = it0.get("description_text") or ""
            if services_desc:
                desc_style = it0.get("style") or {}
                desc_font = (
                    desc_style.get("description_font")
                    or ds_comp_style.get("description_font")
                    or _style(layout, "discount", "description_font", fallback="Helvetica")
                )
                desc_size = float(
                    desc_style.get("description_size")
                    or ds_comp_style.get("description_size")
                    or _style(layout, "discount", "description_size", fallback=10.0)
                )
                desc_leading = float(
                    desc_style.get("description_leading")
                    or ds_comp_style.get("description_leading")
                    or _style(layout, "discount", "description_leading", fallback=12.0)
                )
                desc_color = _hex(
                    desc_style.get("description_color")
                    or ds_comp_style.get("description_color")
                    or desc_style.get("item_price_color")
                    or ds_comp_style.get("item_price_color"),
                    _string_hex(_COLOR_INK),
                )
                _draw_wrapped_centered(pdf, services_desc, w / 2,
                                       services_panel_y + 24, w - 160,
                                       desc_font, desc_size, desc_leading, desc_color)

            # Item 2+ → below panel as italic text
            if len(ds_items) > 1:
                it1 = ds_items[1]
                note_style = it1.get("style") or {}
                note_font = (
                    note_style.get("note_font")
                    or ds_comp_style.get("note_font")
                    or _style(layout, "discount", "note_font", fallback="Helvetica-BoldOblique")
                )
                note_size = float(
                    note_style.get("note_size")
                    or ds_comp_style.get("note_size")
                    or _style(layout, "discount", "note_size", fallback=13.0)
                )
                note_color = _hex(
                    note_style.get("note_color")
                    or ds_comp_style.get("note_color")
                    or _style(layout, "discount", "note_color", fallback=None),
                    _string_hex(_COLOR_WHITE),
                )
                _draw_centered(pdf, it1.get("item_name") or "", w / 2,
                               services_panel_y - 16,
                               note_font, note_size, note_color)

    # ----- Footer contact line (inside weekday panel, very bottom) -----
    footer_text = ev.get("footer") or ""
    if footer_text:
        footer_text_color = _hex(ev.get("footer_text_color"), _string_hex(secondary_text_color))
        footer_font_size = float(ev.get("footer_font_size") or 10)
        _draw_centered(pdf, footer_text, w / 2, secondary_region["y"] + 6,
                       "Helvetica-Bold", footer_font_size, footer_text_color)

    # ----- Legal strip (below weekday panel) -----
    _draw_rounded_panel(pdf, legal_region["x"], legal_region["y"], legal_region["w"], legal_region["h"],
                        palette["legal_bg"], palette["legal_border"], radius=10, stroke_w=1)

    legal_text = ""
    if legal:
        legal_text = legal[0].get("description_text") or ""
    if not legal_text:
        legal_text = ev.get("legal") or ""
    if legal_text:
        _draw_centered(pdf, legal_text, w / 2, legal_region["y"] + 7,
                       "Helvetica-Bold", 10, _COLOR_INK)

    campaign_footnote = (ctx.get("campaign_footnote_text") or "").strip()
    footer_notes: list[str] = []
    if campaign_footnote:
        footer_notes = [f"** {campaign_footnote}"]
    if footer_notes:
        note_y = footnote_region["y"]
        max_notes = int(_style(layout, "footnotes", "max_campaign_notes", fallback=2))
        for note in footer_notes[:max_notes]:
            _draw_wrapped_centered(pdf, note, w / 2, note_y, footnote_region["w"], "Helvetica", 8.5, 9.5, _COLOR_INK)
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
        section_fill = _hex(comp.get("background_color"), _string_hex(palette["accent"]))
        pdf.setFillColor(section_fill)
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

            item_fill_raw = item.get("background_color")
            if item_fill_raw:
                item_fill = _hex(item_fill_raw, _string_hex(palette["primary_light"]))
                pdf.setFillColor(item_fill)
                pdf.roundRect(_MARGIN + 8, y - 5, w - (_MARGIN + 8) * 2, 16, 6, fill=1, stroke=0)

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
            "render_region": "featured",
            "render_mode": "offer-card-grid",
            "style": {},
            "display_title": "Offer Details",
            "background_color": None,
            "header_accent_color": None,
            "subtitle": None,
            "description_text": None,
            "display_order": 0,
            "items": [
                {
                    "item_name": offer.get("offer_name"),
                    "item_kind": offer.get("offer_type") or "service",
                    "render_role": None,
                    "style": {},
                    "duration_label": None,
                    "item_value": offer.get("offer_value"),
                    "background_color": None,
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
        SELECT id, component_key, component_kind, render_region, render_mode, style_json, display_title, background_color, header_accent_color, footnote_text, subtitle, description_text, display_order
        FROM campaign_components
        WHERE campaign_id = ?
        ORDER BY display_order ASC, id ASC;
        """,
        (campaign_id,),
    ).fetchall()

    binding = connection.execute(
        """
        SELECT t.template_name, t.template_kind, t.size_spec, t.layout_json,
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
    template: dict[str, Any] = {"layout": {}}
    if binding is not None:
        defaults = json.loads(binding["default_values_json"] or "{}")
        overrides = json.loads(binding["override_values_json"] or "{}")
        effective = {**defaults, **overrides}
        template_name = binding["template_name"]
        template = {
            "template_name": binding["template_name"],
            "template_kind": binding["template_kind"],
            "size_spec": binding["size_spec"],
            "layout": json.loads(binding["layout_json"] or "{}"),
            "default_values": defaults,
            "override_values": overrides,
        }

    offer_payloads = [dict(o) for o in offers]
    component_payloads: list[dict[str, Any]] = []
    for component in components:
        items = connection.execute(
            """
            SELECT item_name, item_kind, duration_label, item_value, background_color, render_role, style_json, description_text, terms_text, display_order
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
                "render_region": component["render_region"],
                "render_mode": component["render_mode"],
                "style": json.loads(component["style_json"] or "{}"),
                "display_title": component["display_title"],
                "background_color": component["background_color"],
                "header_accent_color": component["header_accent_color"],
                "footnote_text": component["footnote_text"],
                "subtitle": component["subtitle"],
                "description_text": component["description_text"],
                "display_order": component["display_order"],
                "items": [
                    {
                        **dict(item),
                        "style": json.loads(item["style_json"] or "{}"),
                    }
                    for item in items
                ],
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
        "template": template,
    }


def _collect_render_context_session(db: Session, campaign_id: int) -> dict[str, Any]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise ValueError(f"Campaign {campaign_id} not found")

    business = campaign.business
    default_theme = next(
        (
            theme
            for theme in sorted(business.brand_themes, key=lambda item: item.id)
            if theme.name == "default"
        ),
        None,
    )
    location = next(iter(sorted(business.locations, key=lambda item: item.id)), None)
    contacts = sorted(business.contacts, key=lambda item: (not item.is_primary, item.id))
    offers = sorted(campaign.offers, key=lambda item: item.id)
    components = sorted(campaign.components, key=lambda item: (item.display_order, item.id))
    binding = (
        db.query(CampaignTemplateBinding)
        .filter(
            CampaignTemplateBinding.campaign_id == campaign_id,
            CampaignTemplateBinding.is_active.is_(True),
        )
        .order_by(CampaignTemplateBinding.id.desc())
        .first()
    )

    effective: dict[str, Any] = {}
    template_name = None
    template: dict[str, Any] = {"layout": {}}
    if binding is not None:
        defaults = json.loads(binding.template.default_values_json or "{}")
        overrides = json.loads(binding.override_values_json or "{}")
        effective = {**defaults, **overrides}
        template_name = binding.template.template_name
        template = {
            "template_name": binding.template.template_name,
            "template_kind": binding.template.template_kind,
            "size_spec": binding.template.size_spec,
            "layout": json.loads(binding.template.layout_json or "{}"),
            "default_values": defaults,
            "override_values": overrides,
        }

    offer_payloads = [
        {
            "offer_name": offer.offer_name,
            "offer_type": offer.offer_type,
            "offer_value": offer.offer_value,
            "start_date": offer.start_date,
            "end_date": offer.end_date,
            "terms_text": offer.terms_text,
        }
        for offer in offers
    ]

    component_payloads: list[dict[str, Any]] = []
    for component in components:
        items = sorted(component.items, key=lambda item: (item.display_order, item.id))
        component_payloads.append(
            {
                "component_key": component.component_key,
                "component_kind": component.component_kind,
                "render_region": component.render_region,
                "render_mode": component.render_mode,
                "style": json.loads(component.style_json or "{}"),
                "display_title": component.display_title,
                "background_color": component.background_color,
                "header_accent_color": component.header_accent_color,
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
                        "background_color": item.background_color,
                        "render_role": item.render_role,
                        "style_json": item.style_json,
                        "description_text": item.description_text,
                        "terms_text": item.terms_text,
                        "display_order": item.display_order,
                        "style": json.loads(item.style_json or "{}"),
                    }
                    for item in items
                ],
            }
        )
    if not component_payloads:
        component_payloads = _fallback_components(offer_payloads)

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign.campaign_name,
        "title": campaign.title,
        "objective": campaign.objective,
        "campaign_footnote_text": campaign.footnote_text,
        "start_date": campaign.start_date,
        "end_date": campaign.end_date,
        "business_display_name": business.display_name,
        "business_legal_name": business.legal_name,
        "theme": {
            "primary_color": default_theme.primary_color,
            "secondary_color": default_theme.secondary_color,
            "accent_color": default_theme.accent_color,
            "font_family": default_theme.font_family,
            "logo_path": default_theme.logo_path,
        }
        if default_theme
        else {},
        "location": {
            "line1": location.line1,
            "line2": location.line2,
            "city": location.city,
            "state": location.state,
            "postal_code": location.postal_code,
        }
        if location
        else None,
        "contacts": [
            {
                "contact_type": contact.contact_type,
                "contact_value": contact.contact_value,
                "is_primary": contact.is_primary,
            }
            for contact in contacts
        ],
        "offers": offer_payloads,
        "components": component_payloads,
        "effective_values": effective,
        "template_name": template_name,
        "template": template,
    }


# ---------------------------------------------------------------------------
# Public render API
# ---------------------------------------------------------------------------

def render_flyer(ctx: dict[str, Any], data_dir: Path | None = None) -> bytes:
    palette = _palette(ctx)
    layout = _layout(ctx)
    grouped = _components_by_region(ctx, layout)

    featured = _region_components(grouped, "featured", {"offer-card-grid"})
    weekday = _region_components(grouped, "secondary", {"strip-list"})
    discount = _region_components(grouped, "discount", {"discount-panel"})
    legal = _region_components(grouped, "legal", {"legal-text"})
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


def render_flyer_nup(ctx: dict[str, Any], images_per_page: int, data_dir: Path | None = None) -> bytes:
    if images_per_page < 2:
        raise ValueError("images_per_page must be >= 2")

    palette = _palette(ctx)
    layout = _layout(ctx)
    grouped = _components_by_region(ctx, layout)

    featured = _region_components(grouped, "featured", {"offer-card-grid"})
    weekday = _region_components(grouped, "secondary", {"strip-list"})
    discount = _region_components(grouped, "discount", {"discount-panel"})
    legal = _region_components(grouped, "legal", {"legal-text"})
    use_rich = bool(featured or weekday)

    logo_reader = None
    if use_rich:
        logo_path = _resolve_logo(
            ctx.get("theme", {}),
            data_dir,
            ctx.get("business_display_name", ""),
        )
        logo_reader = _load_logo(logo_path)

    cols = math.ceil(math.sqrt(images_per_page))
    rows = math.ceil(images_per_page / cols)
    cell_w = _PW / cols
    cell_h = _PH / rows
    scale = min(cell_w / _PW, cell_h / _PH)
    frame_w = _PW * scale
    frame_h = _PH * scale

    buf = BytesIO()
    pdf = rl_canvas.Canvas(buf, pagesize=letter)
    pdf.setTitle(f"{ctx.get('title') or 'Flyer'} ({images_per_page}-up)")

    for index in range(images_per_page):
        row = index // cols
        col = index % cols

        origin_x = (col * cell_w) + ((cell_w - frame_w) / 2)
        origin_y = _PH - ((row + 1) * cell_h) + ((cell_h - frame_h) / 2)

        pdf.saveState()
        pdf.translate(origin_x, origin_y)
        pdf.scale(scale, scale)

        if use_rich:
            _draw_rich_flyer(pdf, ctx, palette, logo_reader, featured, weekday, discount, legal)
        else:
            _draw_simple_flyer(pdf, ctx, palette)

        pdf.restoreState()

    pdf.showPage()
    pdf.save()
    return buf.getvalue()


def _file_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _slug(text: str | None) -> str:
    """Standard slugifier for filenames."""
    if not text:
        return "unnamed"
    # Replace non-alphanumeric with hyphen, then collapse hyphens.
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return slug.strip("-")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to a file atomically by using a temporary file."""
    import tempfile
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def render_campaign_artifact(
    connection: sqlite3.Connection,
    campaign_id: int,
    output_dir: Path,
    artifact_type: str = "flyer",
    data_dir: Path | None = None,
    images_per_page: int | None = None,
    overwrite: bool = False,
    custom_name: str | None = None,
) -> list[dict[str, Any]]:
    """Generates and registers campaign artifacts (PDFs) with strict company-campaign naming."""
    ctx = _collect_render_context(connection, campaign_id)

    if artifact_type not in {"flyer", "poster"}:
        raise ValueError(f"Unsupported artifact_type '{artifact_type}'")

    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Naming convention: company-campaign.pdf
    if custom_name:
        # Enforce basic safety: no path traversal
        clean_name = Path(custom_name).name
        if clean_name.lower().endswith(".pdf"):
            clean_name = clean_name[:-4]
        base_name = _slug(clean_name)
    else:
        company_slug = _slug(ctx["business_display_name"])
        campaign_slug = _slug(ctx["campaign_name"])
        base_name = f"{company_slug}-{campaign_slug}"
    
    filename = (
        f"{base_name}.pdf"
        if artifact_type == "flyer"
        else f"{base_name}-{artifact_type}.pdf"
    )
    file_path = output_dir / filename

    # Check for file existence before any rendering
    if not overwrite and file_path.exists():
        raise ValueError(filename)

    # Check N-up filename if applicable
    nup_file_path: Path | None = None
    if artifact_type == "flyer" and images_per_page is not None:
        nup_filename = f"{base_name}-{images_per_page}p.pdf"
        nup_file_path = output_dir / nup_filename
        if not overwrite and nup_file_path.exists():
            raise ValueError(nup_filename)

    # 1. Primary Render
    pdf_bytes = render_flyer(ctx, data_dir=data_dir)
    checksum = _file_checksum(pdf_bytes)
    _atomic_write_bytes(file_path, pdf_bytes)

    template_snapshot = json.dumps(
        {
            "template_name": ctx["template_name"],
            "template": ctx.get("template") or {},
            "effective_values": ctx["effective_values"],
        }
    )

    # Register Primary Artifact
    cursor = connection.execute(
        """
        INSERT INTO generated_artifacts
          (campaign_id, artifact_type, file_path, checksum, status, template_snapshot_json)
        VALUES (?, ?, ?, ?, 'complete', ?);
        """,
        (campaign_id, artifact_type, str(file_path), checksum, template_snapshot),
    )
    primary_id = int(cursor.lastrowid)
    
    results = [
        {
            "id": primary_id,
            "campaign_id": campaign_id,
            "artifact_type": artifact_type,
            "file_path": str(file_path),
            "checksum": checksum,
            "status": "complete",
        }
    ]

    # 2. Secondary Render (N-up) if requested
    if artifact_type == "flyer" and images_per_page is not None and nup_file_path:
        nup_bytes = render_flyer_nup(ctx, images_per_page, data_dir=data_dir)
        _atomic_write_bytes(nup_file_path, nup_bytes)
        nup_checksum = _file_checksum(nup_bytes)
        
        # Register Secondary Artifact
        cursor = connection.execute(
            """
            INSERT INTO generated_artifacts
              (campaign_id, artifact_type, file_path, checksum, status, template_snapshot_json)
            VALUES (?, ?, ?, ?, 'complete', ?);
            """,
            (campaign_id, artifact_type, str(nup_file_path), nup_checksum, template_snapshot),
        )
        results.append({
            "id": int(cursor.lastrowid),
            "campaign_id": campaign_id,
            "artifact_type": artifact_type,
            "file_path": str(nup_file_path),
            "checksum": nup_checksum,
            "status": "complete",
        })

    return results


def render_campaign_artifact_session(
    db: Session,
    campaign_id: int,
    output_dir: Path,
    artifact_type: str = "flyer",
    data_dir: Path | None = None,
    images_per_page: int | None = None,
    overwrite: bool = False,
    custom_name: str | None = None,
) -> list[dict[str, Any]]:
    """Generates and registers campaign artifacts using the SQLAlchemy session path."""
    ctx = _collect_render_context_session(db, campaign_id)

    if artifact_type not in {"flyer", "poster"}:
        raise ValueError(f"Unsupported artifact_type '{artifact_type}'")

    output_dir.mkdir(parents=True, exist_ok=True)

    if custom_name:
        clean_name = Path(custom_name).name
        if clean_name.lower().endswith(".pdf"):
            clean_name = clean_name[:-4]
        base_name = _slug(clean_name)
    else:
        company_slug = _slug(ctx["business_display_name"])
        campaign_slug = _slug(ctx["campaign_name"])
        base_name = f"{company_slug}-{campaign_slug}"

    filename = f"{base_name}.pdf" if artifact_type == "flyer" else f"{base_name}-{artifact_type}.pdf"
    file_path = output_dir / filename

    if not overwrite and file_path.exists():
        raise ValueError(filename)

    nup_file_path: Path | None = None
    if artifact_type == "flyer" and images_per_page is not None:
        nup_filename = f"{base_name}-{images_per_page}p.pdf"
        nup_file_path = output_dir / nup_filename
        if not overwrite and nup_file_path.exists():
            raise ValueError(nup_filename)

    pdf_bytes = render_flyer(ctx, data_dir=data_dir)
    checksum = _file_checksum(pdf_bytes)
    _atomic_write_bytes(file_path, pdf_bytes)

    template_snapshot = json.dumps(
        {
            "template_name": ctx["template_name"],
            "template": ctx.get("template") or {},
            "effective_values": ctx["effective_values"],
        }
    )

    primary = GeneratedArtifact(
        campaign_id=campaign_id,
        artifact_type=artifact_type,
        file_path=str(file_path),
        checksum=checksum,
        status="complete",
        template_snapshot_json=template_snapshot,
    )
    db.add(primary)
    db.flush()

    results = [
        {
            "id": primary.id,
            "campaign_id": campaign_id,
            "artifact_type": artifact_type,
            "file_path": str(file_path),
            "checksum": checksum,
            "status": "complete",
        }
    ]

    if artifact_type == "flyer" and images_per_page is not None and nup_file_path:
        nup_bytes = render_flyer_nup(ctx, images_per_page, data_dir=data_dir)
        _atomic_write_bytes(nup_file_path, nup_bytes)
        nup_checksum = _file_checksum(nup_bytes)

        nup = GeneratedArtifact(
            campaign_id=campaign_id,
            artifact_type=artifact_type,
            file_path=str(nup_file_path),
            checksum=nup_checksum,
            status="complete",
            template_snapshot_json=template_snapshot,
        )
        db.add(nup)
        db.flush()
        results.append(
            {
                "id": nup.id,
                "campaign_id": campaign_id,
                "artifact_type": artifact_type,
                "file_path": str(nup_file_path),
                "checksum": nup_checksum,
                "status": "complete",
            }
        )

    return results
