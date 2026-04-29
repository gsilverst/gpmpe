from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
import sqlite3
import uuid
from typing import Any, Literal

from fastapi import HTTPException


CAMPAIGN_STATUS_VALUES = {"draft", "active", "paused", "completed", "archived"}
CAMPAIGN_FIELDS = {"title", "objective", "footnote_text", "status", "start_date", "end_date"}
OFFER_FIELDS = {"offer_value", "start_date", "end_date", "terms_text"}
BRAND_FIELDS = {"primary_color", "secondary_color", "accent_color", "font_family", "logo_path"}
COMPONENT_FIELDS = {
    "component_key",
    "component_kind",
    "display_title",
    "background_color",
    "header_accent_color",
    "subtitle",
    "description_text",
    "footnote_text",
}
COMPONENT_ITEM_FIELDS = {
    "item_name",
    "item_kind",
    "duration_label",
    "item_value",
    "background_color",
    "description_text",
    "terms_text",
}
TEMPLATE_OVERRIDE_FIELDS = {"footer_font_size", "footer_text_color"}

_COMPONENT_RENDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "featured-offers": ("featured", "offer-card-grid"),
    "weekday-specials": ("secondary", "strip-list"),
    "other-offers": ("secondary", "strip-list"),
    "secondary-offers": ("secondary", "strip-list"),
    "discount-strip": ("discount", "discount-panel"),
    "legal-note": ("legal", "legal-text"),
}
BUSINESS_FIELDS = {
    "legal_name",
    "display_name",
    "timezone",
    "is_active",
    "phone",
    "address_line1",
    "address_line2",
    "city",
    "state",
    "postal_code",
    "country",
}

# Alias maps: short/natural names → canonical field name
_CAMPAIGN_FIELD_ALIASES: dict[str, str] = {
    "title": "title", "headline": "title", "header": "title",
    "objective": "objective", "goal": "objective",
    "footnote_text": "footnote_text", "footnote": "footnote_text", "note": "footnote_text",
    "status": "status",
    "start_date": "start_date", "start": "start_date", "starts": "start_date",
    "end_date": "end_date", "end": "end_date", "ends": "end_date",
}
_OFFER_FIELD_ALIASES: dict[str, str] = {
    "offer_value": "offer_value", "value": "offer_value", "discount": "offer_value", "amount": "offer_value",
    "start_date": "start_date", "start": "start_date", "starts": "start_date",
    "end_date": "end_date", "end": "end_date", "ends": "end_date",
    "terms_text": "terms_text", "terms": "terms_text",
}
_BRAND_FIELD_ALIASES: dict[str, str] = {
    "primary_color": "primary_color", "primary": "primary_color",
    "secondary_color": "secondary_color", "secondary": "secondary_color",
    "accent_color": "accent_color", "accent": "accent_color",
    "font_family": "font_family", "font": "font_family",
    "logo_path": "logo_path", "logo": "logo_path",
}
_ITEM_FIELD_ALIASES: dict[str, str] = {
    "item_name": "item_name", "name": "item_name",
    "item_kind": "item_kind", "kind": "item_kind", "type": "item_kind",
    "duration_label": "duration_label", "duration": "duration_label",
    "item_value": "item_value", "value": "item_value", "price": "item_value", "cost": "item_value",
    "background_color": "background_color", "background color": "background_color", "color of the background": "background_color", "color_of_the_background": "background_color", "bg color": "background_color", "bg": "background_color",
    "description_text": "description_text", "description": "description_text", "desc": "description_text",
    "terms_text": "terms_text", "terms": "terms_text",
}
_COMPONENT_FIELD_ALIASES: dict[str, str] = {
    "component_key": "component_key", "key": "component_key", "name": "component_key",
    "component_kind": "component_kind", "kind": "component_kind", "type": "component_kind",
    "display_title": "display_title", "display title": "display_title", "title": "display_title",
    "background_color": "background_color", "background color": "background_color", "color of the background": "background_color", "color_of_the_background": "background_color", "bg color": "background_color", "bg": "background_color",
    "header_accent_color": "header_accent_color", "header accent color": "header_accent_color", "header_accent": "header_accent_color", "header accent": "header_accent_color", "accent header color": "header_accent_color", "accent_header_color": "header_accent_color", "text color": "header_accent_color", "text_color": "header_accent_color", "title color": "header_accent_color", "title_color": "header_accent_color",
    "subtitle": "subtitle", "subheading": "subtitle",
    "description_text": "description_text", "description": "description_text", "desc": "description_text",
    "footnote_text": "footnote_text", "footnote": "footnote_text", "note": "footnote_text",
}
_BUSINESS_FIELD_ALIASES: dict[str, str] = {
    "legal_name": "legal_name", "legal name": "legal_name",
    "display_name": "display_name", "display name": "display_name", "business name": "display_name", "name": "display_name",
    "timezone": "timezone", "time zone": "timezone",
    "is_active": "is_active", "active": "is_active", "enabled": "is_active",
    "phone": "phone", "phone number": "phone",
    "address_line1": "address_line1", "address line 1": "address_line1", "street": "address_line1", "street address": "address_line1",
    "address_line2": "address_line2", "address line 2": "address_line2", "suite": "address_line2", "unit": "address_line2",
    "city": "city",
    "state": "state", "province": "state",
    "postal_code": "postal_code", "postal code": "postal_code", "zip": "postal_code", "zip code": "postal_code",
    "country": "country",
}
_TEMPLATE_OVERRIDE_FIELD_ALIASES: dict[str, str] = {
    "footer_font_size": "footer_font_size",
    "footer font size": "footer_font_size",
    "footer size": "footer_font_size",
    "contact_font_size": "footer_font_size",
    "contact font size": "footer_font_size",
    "footer_text_color": "footer_text_color",
    "footer text color": "footer_text_color",
    "footer color": "footer_text_color",
    "contact_text_color": "footer_text_color",
    "contact text color": "footer_text_color",
    "contact color": "footer_text_color",
}


def _normalize_field(alias: str, alias_map: dict[str, str]) -> str | None:
    """Return the canonical field name for an alias, or None if unrecognised."""
    return alias_map.get(alias.lower().replace("-", "_").replace(" ", "_"))


# Build alternation groups sorted longest-first to avoid partial matches.
def _aliases_regex(alias_map: dict[str, str]) -> str:
    return "|".join(sorted(alias_map.keys(), key=len, reverse=True))


_CAMPAIGN_FIELD_RE = _aliases_regex(_CAMPAIGN_FIELD_ALIASES)
_OFFER_FIELD_RE = _aliases_regex(_OFFER_FIELD_ALIASES)
_BRAND_FIELD_RE = _aliases_regex(_BRAND_FIELD_ALIASES)
_ITEM_FIELD_RE = _aliases_regex(_ITEM_FIELD_ALIASES)
_COMPONENT_FIELD_RE = _aliases_regex(_COMPONENT_FIELD_ALIASES)
_BUSINESS_FIELD_RE = _aliases_regex(_BUSINESS_FIELD_ALIASES)
_TEMPLATE_OVERRIDE_FIELD_RE = _aliases_regex(_TEMPLATE_OVERRIDE_FIELD_ALIASES)

# Matches: "clone <source> [and] rename [it] to <new_name> [for <business>]"
# Also accepts more verbose natural-language phrasings ("cloning the X ... renaming it to Y").
_CLONE_PATTERN = re.compile(
    r"clon(?:e|ing)\s+(?:the\s+)?(?P<source>[A-Za-z0-9._-]+)"
    r"(?:.*?renam(?:e|ing)(?:\s+it)?\s+to\s+(?P<new_name>[A-Za-z0-9._-]+))"
    r"(?:.*?(?:for\s+(?P<business>[A-Za-z0-9._-]+)))?",
    re.IGNORECASE | re.DOTALL,
)

CAMPAIGN_PATTERN = re.compile(
    r"^(?:set|change|update)\s+(?:the\s+)?(?P<field>" + _CAMPAIGN_FIELD_RE + r")(?:\s+field)?\s+to\s+(?P<value>.+)$",
    re.IGNORECASE,
)
OFFER_PATTERN = re.compile(
    r"^set\s+offer\s+(?P<offer_id>\d+)\s+(?P<field>" + _OFFER_FIELD_RE + r")(?:\s+field)?\s+to\s+(?P<value>.+)$",
    re.IGNORECASE,
)
BRAND_PATTERN = re.compile(
    r"^(?:set|change|update)\s+(?:the\s+)?brand\s+(?P<field>" + _BRAND_FIELD_RE + r")(?:\s+field)?\s+to\s+(?P<value>.+)$",
    re.IGNORECASE,
)
BUSINESS_PATTERN = re.compile(
    r"^(?:set|change|update)\s+(?:the\s+)?(?:business|business\s+profile|profile)\s+(?P<field>" + _BUSINESS_FIELD_RE + r")(?:\s+field)?\s+to\s+(?P<value>.+)$",
    re.IGNORECASE,
)
TEMPLATE_OVERRIDE_PATTERN = re.compile(
    r"^(?:set|change|update)\s+(?:the\s+)?(?:template\s+)?(?P<field>"
    + _TEMPLATE_OVERRIDE_FIELD_RE
    + r")(?:\s+field)?\s+to\s+(?P<value>.+)$",
    re.IGNORECASE,
)
COMPONENT_ITEM_CHANGE_FIELD_PATTERN = re.compile(
    r"^(?:change|set|update)\s+(?:the\s+)?"
    r"(?P<field>" + _ITEM_FIELD_RE + r")"
    r"(?:\s+field)?"
    r"\s+(?:of\s+)?(?:the\s+)?(?P<item>.+?)\s+items?"
    r"(?:\s+in\s+(?:the\s+)?(?P<component>.+?)\s+components?)?"
    r"\s+to\s+(?P<value>.+)$",
    re.IGNORECASE,
)
COMPONENT_ITEM_CHANGE_FIELD_ITEM_FIRST_PATTERN = re.compile(
    r"^(?:change|set|update)\s+(?:the\s+)?"
    r"(?P<item>.+?)\s+items?\s+"
    r"(?P<field>" + _ITEM_FIELD_RE + r")"
    r"(?:\s+field)?"
    r"(?:\s+in\s+(?:the\s+)?(?P<component>.+?)\s+components?)?"
    r"\s+to\s+(?P<value>.+)$",
    re.IGNORECASE,
)
COMPONENT_ITEM_CHANGE_ALL_PATTERN = re.compile(
    r"^(?:change|set|update)\s+(?:the\s+)?"
    r"(?P<field>" + _ITEM_FIELD_RE + r")"
    r"(?:\s+field)?"
    r"\s+to\s+(?P<value>.+?)"
    r"\s+for\s+all\s+items"
    r"(?:\s+in\s+(?:the\s+)?(?P<component>.+?)\s+components?)?"
    r"[.!?]?$",
    re.IGNORECASE,
)
COMPONENT_CHANGE_ALL_PATTERN = re.compile(
    r"^(?:change|set|update)\s+(?:the\s+)?"
    r"(?P<field>" + _COMPONENT_FIELD_RE + r")"
    r"(?:\s+field)?"
    r"\s+to\s+(?P<value>.+?)"
    r"\s+for\s+all\s+components"
    r"[.!?]?$",
    re.IGNORECASE,
)
COMPONENT_SET_PATTERN = re.compile(
    r"^(?:set|change|update)\s+components?\s+(?P<component>.+?)\s+(?P<field>" + _COMPONENT_FIELD_RE + r")(?:\s+field)?\s+to\s+(?P<value>.+)$",
    re.IGNORECASE,
)
COMPONENT_CHANGE_FIELD_PATTERN = re.compile(
    r"^(?:change|set|update)\s+(?:the\s+)?(?P<field>" + _COMPONENT_FIELD_RE + r")"
    r"(?:\s+field)?\s+of\s+(?:the\s+)?(?P<component>.+?)\s+components?\s+to\s+(?P<value>.+)$",
    re.IGNORECASE,
)
COMPONENT_CHANGE_NAME_PATTERN = re.compile(
    r"^change\s+the\s+name\s+of\s+(?:the\s+)?(.+?)\s+components?\s+to\s+(.+)$",
    re.IGNORECASE,
)
COMPONENT_CHANGE_NAME_INCOMPLETE_PATTERN = re.compile(
    r"^change\s+the\s+name\s+of\s+(?:the\s+)?(.+?)\s+components?\s*[.!?]?$",
    re.IGNORECASE,
)
COMPONENT_CHANGE_KEY_FIELD_PATTERN = re.compile(
    r"^change\s+(?:the\s+)?component[-_\s]?key\s+field\s+of\s+(?:the\s+)?(.+?)\s+components?\s+to\s+(.+)$",
    re.IGNORECASE,
)
COMPONENT_CHANGE_KEY_FIELD_INCOMPLETE_PATTERN = re.compile(
    r"^change\s+(?:the\s+)?component[-_\s]?key\s+field\s+of\s+(?:the\s+)?(.+?)\s+components?\s*[.!?]?$",
    re.IGNORECASE,
)
COMPONENT_RENAME_PATTERN = re.compile(
    r"^rename\s+(?:the\s+)?components?\s+(.+?)\s+to\s+(.+)$",
    re.IGNORECASE,
)
COMPONENT_FIELD_DELETE_PATTERN = re.compile(
    r"^delete\s+(?:the\s+)?(?P<field>" + _COMPONENT_FIELD_RE + r")"
    r"(?:\s+field)?"
    r"\s+(?:for|of|in)\s+(?:the\s+)?(?P<component>.+?)\s+components?$",
    re.IGNORECASE,
)
COMPONENT_DELETE_PATTERN = re.compile(
    r"^delete\s+(?:the\s+)?(.+?)\s+components?$",
    re.IGNORECASE,
)
COMPONENT_ITEM_DELETE_PATTERN = re.compile(
    r"^delete\s+(?:the\s+)?(.+?)\s+items?(?:\s+in\s+(?:the\s+)?(.+?)\s+components?)?$",
    re.IGNORECASE,
)
COMPONENT_ITEM_CLONE_PATTERN = re.compile(
    r"^create\s+a\s+new\s+item\s+like\s+(?:the\s+)?(?P<source>.+?)\s+items?"
    r"(?:\s+called\s+(?P<name>.+?))?"
    r"\s+(?:and\s+add\s+it\s+)?between\s+(?:the\s+)?(?P<left>.+?)(?:\s+items?)?"
    r"\s+and\s+(?:the\s+)?(?P<right>.+?)\s+items?"
    r"(?:\s+in\s+(?:the\s+)?(?P<component>.+?)\s+components?)?$",
    re.IGNORECASE,
)
COMPONENT_ITEM_ADD_PATTERN = re.compile(
    r"^(?:add|create)\s+(?:an?\s+|the\s+)?(?:new\s+)?items?"
    r"(?:\s+called\s+(?P<name>.+?))?"
    r"(?:\s+like\s+(?:the\s+)?(?P<source>.+?)\s+items?)?"
    r"(?:\s+(?:to|in|into)\s+(?:the\s+)?(?P<component>.+?)\s+components?)?"
    r"(?:\s+(?P<position>before|after)\s+(?:the\s+)?(?P<relative>.+?)\s+items?)?"
    r"(?:\s+(?:to|in|into)\s+(?:the\s+)?(?P<component2>.+?)\s+components?)?$",
    re.IGNORECASE,
)
COMPONENT_CONTEXT_PATTERN = re.compile(
    r"^(?:i\s+am\s+working\s+on|i'?m\s+working\s+on|set\s+(?:the\s+)?active\s+components?\s+to|use)\s+(?:the\s+)?(.+?)\s+components?[.!?]?$",
    re.IGNORECASE,
)
LIST_COMPONENTS_PATTERN = re.compile(
    r"^(?:what\s+are\s+(?:the\s+)?|list\s+(?:the\s+)?|show\s+(?:me\s+)?(?:the\s+)?)components?"
    r"(?:\s+of\s+(?:the\s+)?(?:current|active|this)\s+(?:promotion|campaign))?[.!?]?$",
    re.IGNORECASE,
)
LIST_ITEMS_PATTERN = re.compile(
    r"^(?:what\s+are\s+(?:the\s+)?|list\s+(?:the\s+)?|show\s+(?:me\s+)?(?:the\s+)?)items?"
    r"(?:\s+(?:of|in)\s+(?:the\s+)?(?:current|active|this)\s+components?)?[.!?]?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedCommand:
    target: Literal["campaign", "offer", "brand", "business", "component", "component_item", "template_override", "clarify"]
    field: str
    value: str
    offer_id: int | None = None
    component_ref: str | None = None
    item_ref: str | None = None
    secondary_item_ref: str | None = None
    tertiary_item_ref: str | None = None


@dataclass(frozen=True)
class ParsedCloneCommand:
    source_campaign_name: str  # slug of the campaign to clone
    new_campaign_name: str     # slug for the new campaign
    business_name: str | None  # optional business slug hint from the message


@dataclass(frozen=True)
class ParsedContextCommand:
    context_type: Literal["component"]
    component_ref: str


@dataclass(frozen=True)
class ParsedQueryCommand:
    query_type: Literal["list_components", "list_items"]


class ChatSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, list[dict[str, str]]] = {}
        self._contexts: dict[str, dict[str, Any]] = {}

    def create(self) -> str:
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = []
        self._contexts[session_id] = {}
        return session_id

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def append(self, session_id: str, role: str, content: str) -> None:
        if session_id not in self._sessions:
            raise KeyError(session_id)
        self._sessions[session_id].append({"role": role, "content": content})

    def history(self, session_id: str) -> list[dict[str, str]]:
        if session_id not in self._sessions:
            raise KeyError(session_id)
        return list(self._sessions[session_id])

    def get_context(self, session_id: str) -> dict[str, Any]:
        if session_id not in self._contexts:
            raise KeyError(session_id)
        return dict(self._contexts[session_id])

    def set_context_value(self, session_id: str, key: str, value: Any) -> None:
        if session_id not in self._contexts:
            raise KeyError(session_id)
        self._contexts[session_id][key] = value


def parse_clone_command(message: str) -> ParsedCloneCommand | None:
    """Return a ParsedCloneCommand if the message expresses a clone intent, else None."""
    match = _CLONE_PATTERN.search(message)
    if match is None:
        return None
    source = match.group("source")
    new_name = match.group("new_name")
    business = match.group("business")
    if not source or not new_name:
        return None
    # Strip trailing punctuation that the regex may have included
    source = source.rstrip(".,;:!?")
    new_name = new_name.rstrip(".,;:!?")
    if business:
        business = business.rstrip(".,;:!?")
    return ParsedCloneCommand(
        source_campaign_name=source,
        new_campaign_name=new_name,
        business_name=business,
    )


def parse_session_context_command(message: str) -> ParsedContextCommand | None:
    text = message.strip()
    match = COMPONENT_CONTEXT_PATTERN.match(text)
    if match is None:
        return None
    component_ref = match.group(1).strip().strip('"\'')
    if component_ref == "":
        return None
    return ParsedContextCommand(context_type="component", component_ref=component_ref)


def parse_query_command(message: str) -> ParsedQueryCommand | None:
    text = message.strip()
    if LIST_COMPONENTS_PATTERN.match(text):
        return ParsedQueryCommand(query_type="list_components")
    if LIST_ITEMS_PATTERN.match(text):
        return ParsedQueryCommand(query_type="list_items")
    return None


def parse_chat_command(message: str) -> ParsedCommand:
    text = message.strip()

    template_override_match = TEMPLATE_OVERRIDE_PATTERN.match(text)
    if template_override_match:
        raw_field = template_override_match.group("field").lower()
        canonical = _normalize_field(raw_field, _TEMPLATE_OVERRIDE_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised template override field: '{raw_field}'")
        value = template_override_match.group("value").strip()
        return ParsedCommand(target="template_override", field=canonical, value=value)

    campaign_match = CAMPAIGN_PATTERN.match(text)
    if campaign_match:
        raw_field = campaign_match.group("field").lower()
        canonical = _normalize_field(raw_field, _CAMPAIGN_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised campaign field: '{raw_field}'")
        value = campaign_match.group("value").strip()
        return ParsedCommand(target="campaign", field=canonical, value=value)

    offer_match = OFFER_PATTERN.match(text)
    if offer_match:
        offer_id = int(offer_match.group("offer_id"))
        raw_field = offer_match.group("field").lower()
        canonical = _normalize_field(raw_field, _OFFER_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised offer field: '{raw_field}'")
        value = offer_match.group("value").strip()
        return ParsedCommand(target="offer", field=canonical, value=value, offer_id=offer_id)

    brand_match = BRAND_PATTERN.match(text)
    if brand_match:
        raw_field = brand_match.group("field").lower()
        canonical = _normalize_field(raw_field, _BRAND_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised brand field: '{raw_field}'")
        value = brand_match.group("value").strip()
        return ParsedCommand(target="brand", field=canonical, value=value)

    business_match = BUSINESS_PATTERN.match(text)
    if business_match:
        raw_field = business_match.group("field").lower()
        canonical = _normalize_field(raw_field, _BUSINESS_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised business field: '{raw_field}'")
        value = business_match.group("value").strip()
        return ParsedCommand(target="business", field=canonical, value=value)

    component_set_match = COMPONENT_SET_PATTERN.match(text)
    if component_set_match:
        component_ref = component_set_match.group("component").strip().strip("\"'")
        raw_field = component_set_match.group("field").lower().strip()
        canonical = _normalize_field(raw_field, _COMPONENT_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised component field: '{raw_field}'")
        value = component_set_match.group("value").strip()
        return ParsedCommand(target="component", field=canonical, value=value, component_ref=component_ref)

    component_change_name_match = COMPONENT_CHANGE_NAME_PATTERN.match(text)
    if component_change_name_match:
        component_ref = component_change_name_match.group(1).strip().strip("\"'")
        value = component_change_name_match.group(2).strip()
        return ParsedCommand(target="component", field="component_key", value=value, component_ref=component_ref)

    if COMPONENT_CHANGE_NAME_INCOMPLETE_PATTERN.match(text):
        return ParsedCommand(
            target="clarify",
            field="message",
            value=(
                "I can do that. Please provide the new component-key, for example: "
                "'change the name of mothers-day-specials component to main-street-appreciation-month'."
            ),
        )

    component_change_key_field_match = COMPONENT_CHANGE_KEY_FIELD_PATTERN.match(text)
    if component_change_key_field_match:
        component_ref = component_change_key_field_match.group(1).strip().strip("\"'")
        value = component_change_key_field_match.group(2).strip()
        return ParsedCommand(target="component", field="component_key", value=value, component_ref=component_ref)

    if COMPONENT_CHANGE_KEY_FIELD_INCOMPLETE_PATTERN.match(text):
        return ParsedCommand(
            target="clarify",
            field="message",
            value=(
                "I can do that. Please provide the new component-key, for example: "
                "'change the component-key field of mothers-day-specials component "
                "to main-street-appreciation-month'."
            ),
        )

    component_rename_match = COMPONENT_RENAME_PATTERN.match(text)
    if component_rename_match:
        component_ref = component_rename_match.group(1).strip().strip("\"'")
        value = component_rename_match.group(2).strip()
        return ParsedCommand(target="component", field="component_key", value=value, component_ref=component_ref)

    component_change_field_match = COMPONENT_CHANGE_FIELD_PATTERN.match(text)
    if component_change_field_match:
        component_ref = component_change_field_match.group("component").strip().strip("\"'")
        raw_field = component_change_field_match.group("field").lower().strip()
        canonical = _normalize_field(raw_field, _COMPONENT_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised component field: '{raw_field}'")
        value = component_change_field_match.group("value").strip()
        return ParsedCommand(target="component", field=canonical, value=value, component_ref=component_ref)

    component_change_all_match = COMPONENT_CHANGE_ALL_PATTERN.match(text)
    if component_change_all_match:
        raw_field = component_change_all_match.group("field").lower().strip()
        canonical = _normalize_field(raw_field, _COMPONENT_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised component field: '{raw_field}'")
        value = component_change_all_match.group("value").strip().rstrip(".!?")
        return ParsedCommand(target="component", field=canonical, value=value, component_ref="__all__")

    component_item_change_match = COMPONENT_ITEM_CHANGE_FIELD_PATTERN.match(text)
    if component_item_change_match:
        raw_field = component_item_change_match.group("field").lower().strip()
        canonical = _normalize_field(raw_field, _ITEM_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised item field: '{raw_field}'")
        item_ref = component_item_change_match.group("item").strip().strip("\"'")
        component_ref = component_item_change_match.group("component")
        component_ref = component_ref.strip().strip("\"'") if component_ref else None
        value = component_item_change_match.group("value").strip()
        return ParsedCommand(
            target="component_item",
            field=canonical,
            value=value,
            component_ref=component_ref,
            item_ref=item_ref,
        )

    component_item_change_item_first_match = COMPONENT_ITEM_CHANGE_FIELD_ITEM_FIRST_PATTERN.match(text)
    if component_item_change_item_first_match:
        raw_field = component_item_change_item_first_match.group("field").lower().strip()
        canonical = _normalize_field(raw_field, _ITEM_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised component item field: '{raw_field}'")
        item_ref = component_item_change_item_first_match.group("item").strip().strip("\"'")
        component_ref = component_item_change_item_first_match.group("component")
        component_ref = component_ref.strip().strip("\"'") if component_ref else None
        value = component_item_change_item_first_match.group("value").strip()
        return ParsedCommand(
            target="component_item",
            field=canonical,
            value=value,
            component_ref=component_ref,
            item_ref=item_ref,
        )

    component_item_change_all_match = COMPONENT_ITEM_CHANGE_ALL_PATTERN.match(text)
    if component_item_change_all_match:
        raw_field = component_item_change_all_match.group("field").lower().strip()
        canonical = _normalize_field(raw_field, _ITEM_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised item field: '{raw_field}'")
        component_ref = component_item_change_all_match.group("component")
        component_ref = component_ref.strip().strip("\"'") if component_ref else None
        value = component_item_change_all_match.group("value").strip().rstrip(".!?")
        return ParsedCommand(
            target="component_item",
            field=canonical,
            value=value,
            component_ref=component_ref,
            item_ref="__all__",
        )

    component_item_delete_match = COMPONENT_ITEM_DELETE_PATTERN.match(text)
    if component_item_delete_match:
        item_ref = component_item_delete_match.group(1).strip().strip("\"'")
        component_ref = component_item_delete_match.group(2)
        component_ref = component_ref.strip().strip("\"'") if component_ref else None
        return ParsedCommand(
            target="component_item",
            field="delete",
            value="",
            component_ref=component_ref,
            item_ref=item_ref,
        )

    component_field_delete_match = COMPONENT_FIELD_DELETE_PATTERN.match(text)
    if component_field_delete_match:
        raw_field = component_field_delete_match.group("field").lower().strip()
        canonical = _normalize_field(raw_field, _COMPONENT_FIELD_ALIASES)
        if canonical is None:
            raise HTTPException(status_code=400, detail=f"Unrecognised component field: '{raw_field}'")
        component_ref = component_field_delete_match.group("component").strip().strip("\"'")
        return ParsedCommand(target="component", field=canonical, value="", component_ref=component_ref)

    component_delete_match = COMPONENT_DELETE_PATTERN.match(text)
    if component_delete_match:
        component_ref = component_delete_match.group(1).strip().strip("\"'")
        return ParsedCommand(target="component", field="delete", value="", component_ref=component_ref)

    component_item_clone_match = COMPONENT_ITEM_CLONE_PATTERN.match(text)
    if component_item_clone_match:
        source_item_ref = component_item_clone_match.group("source").strip().strip("\"'")
        cloned_item_name = component_item_clone_match.group("name")
        cloned_item_name = cloned_item_name.strip().strip("\"'") if cloned_item_name else source_item_ref
        left_item_ref = component_item_clone_match.group("left").strip().strip("\"'")
        right_item_ref = component_item_clone_match.group("right").strip().strip("\"'")
        component_ref = component_item_clone_match.group("component")
        component_ref = component_ref.strip().strip("\"'") if component_ref else None
        return ParsedCommand(
            target="component_item",
            field="clone",
            value=cloned_item_name,
            component_ref=component_ref,
            item_ref=source_item_ref,
            secondary_item_ref=left_item_ref,
            tertiary_item_ref=right_item_ref,
        )

    component_item_add_match = COMPONENT_ITEM_ADD_PATTERN.match(text)
    if component_item_add_match:
        name = component_item_add_match.group("name")
        name = name.strip().strip("\"'") if name else "New Item"
        source = component_item_add_match.group("source")
        source = source.strip().strip("\"'") if source else None
        position = component_item_add_match.group("position")
        relative = component_item_add_match.group("relative")
        relative = relative.strip().strip("\"'") if relative else None
        component_ref = component_item_add_match.group("component") or component_item_add_match.group("component2")
        component_ref = component_ref.strip().strip("\"'") if component_ref else None
        return ParsedCommand(
            target="component_item",
            field="add",
            value=name,
            component_ref=component_ref,
            item_ref=source,
            secondary_item_ref=relative,
            tertiary_item_ref=position,
        )

    raise HTTPException(
        status_code=400,
        detail=(
            "Unsupported edit command. Use one of: "
            "'set <campaign_field> to <value>', "
            "'set offer <offer_id> <offer_field> to <value>', "
            "'set brand <brand_field> to <value>', "
            "'set business <business_field> to <value>', "
            "'add a new item called <name> [like <source> item] [before/after <relative> item] [to <component> component]', "
            "'change the component-key field of <component> component to <new_component_key>', "
            "'change the item_value field of the first item in <component> component to <value>', "
            "'delete the second item', "
            "'delete the Signature Facial item in the main-street-appreciation component', "
            "or 'create a new item like the Swedish Massage item called Lymphatic Drainage and add it between the Swedish Massage and the Deep Tissue items'."
        ),
    )


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}; expected YYYY-MM-DD") from exc


def _offers_overlap(start_a: date, end_a: date, start_b: date, end_b: date) -> bool:
    return start_a <= end_b and start_b <= end_a


def _campaign_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "business_id": row["business_id"],
        "campaign_name": row["campaign_name"],
        "campaign_key": row["campaign_key"] or None,
        "title": row["title"],
        "objective": row["objective"],
        "footnote_text": row["footnote_text"],
        "status": row["status"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
    }


def _parse_boolean_value(value: str, field_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "1", "active", "enabled", "on"}:
        return True
    if normalized in {"false", "no", "0", "inactive", "disabled", "off"}:
        return False
    raise HTTPException(status_code=400, detail=f"Invalid {field_name}; expected true/false")


def _coerce_template_override_value(field_name: str, value: str) -> str | int | float:
    stripped = value.strip()
    if stripped == "":
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty")

    if field_name == "footer_font_size":
        try:
            font_size = float(stripped)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid footer_font_size; expected a number") from exc
        if font_size <= 0:
            raise HTTPException(status_code=400, detail="footer_font_size must be greater than zero")
        return int(font_size) if font_size.is_integer() else font_size

    return stripped


def _business_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "display_name": row["display_name"],
        "timezone": row["timezone"],
        "is_active": bool(row["is_active"]),
        "phone": row["phone"],
        "address_line1": row["address_line1"],
        "address_line2": row["address_line2"],
        "city": row["city"],
        "state": row["state"],
        "postal_code": row["postal_code"],
        "country": row["country"],
    }


def _load_business(connection: Any, business_id: int) -> Any | None:
    return connection.execute(
        """
        SELECT b.id, b.legal_name, b.display_name, b.timezone, b.is_active,
               (
                   SELECT contact_value
                   FROM business_contacts bc
                   WHERE bc.business_id = b.id AND bc.contact_type = 'phone'
                   ORDER BY bc.is_primary DESC, bc.id ASC
                   LIMIT 1
               ) AS phone,
               (
                   SELECT line1
                   FROM business_locations bl
                   WHERE bl.business_id = b.id
                   ORDER BY bl.id ASC
                   LIMIT 1
               ) AS address_line1,
               (
                   SELECT line2
                   FROM business_locations bl
                   WHERE bl.business_id = b.id
                   ORDER BY bl.id ASC
                   LIMIT 1
               ) AS address_line2,
               (
                   SELECT city
                   FROM business_locations bl
                   WHERE bl.business_id = b.id
                   ORDER BY bl.id ASC
                   LIMIT 1
               ) AS city,
               (
                   SELECT state
                   FROM business_locations bl
                   WHERE bl.business_id = b.id
                   ORDER BY bl.id ASC
                   LIMIT 1
               ) AS state,
               (
                   SELECT postal_code
                   FROM business_locations bl
                   WHERE bl.business_id = b.id
                   ORDER BY bl.id ASC
                   LIMIT 1
               ) AS postal_code,
               (
                   SELECT country
                   FROM business_locations bl
                   WHERE bl.business_id = b.id
                   ORDER BY bl.id ASC
                   LIMIT 1
               ) AS country
        FROM businesses b
        WHERE b.id = ?;
        """,
        (business_id,),
    ).fetchone()


def _normalize_component_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower().strip())
    normalized = normalized.strip("-")
    return normalized


def _normalize_item_ref(value: str) -> str:
    normalized = value.strip().strip('"\'').lower()
    if normalized.startswith("the "):
        normalized = normalized[4:].strip()
    if normalized.endswith(" item"):
        normalized = normalized[:-5].strip()
    return normalized


def resolve_component(connection: Any, campaign_id: int, component_ref: str) -> Any | None:
        return connection.execute(
                """
                SELECT id, campaign_id, component_key, component_kind, display_title, background_color, header_accent_color, footnote_text, subtitle, description_text, display_order
                FROM campaign_components
                WHERE campaign_id = ?
                    AND (LOWER(component_key) = LOWER(?) OR LOWER(display_title) = LOWER(?))
                ORDER BY id ASC
                LIMIT 1;
                """,
                (campaign_id, component_ref, component_ref),
        ).fetchone()


def _resolve_item_selector_index(item_ref: str, item_count: int) -> int | None:
    normalized = item_ref.lower().strip()
    if normalized.startswith("the "):
        normalized = normalized[4:].strip()
    ordinal_map = {
        "first": 0,
        "second": 1,
        "third": 2,
        "fourth": 3,
        "fifth": 4,
        "last": item_count - 1,
    }
    if normalized in ordinal_map:
        index = ordinal_map[normalized]
        return index if 0 <= index < item_count else None

    number_match = re.fullmatch(r"(\d+)(?:st|nd|rd|th)?", normalized)
    if number_match:
        index = int(number_match.group(1)) - 1
        return index if 0 <= index < item_count else None

    return None


def _find_component_item(items: list[Any], item_ref: str) -> Any | None:
    item_index = _resolve_item_selector_index(item_ref, len(items))
    if item_index is not None:
        return items[item_index]

    normalized_ref = _normalize_item_ref(item_ref)

    for item in items:
        if _normalize_item_ref(str(item["item_name"])) == normalized_ref:
            return item

    return None


def _resequence_component_items(connection: Any, component_id: int) -> None:
    items = connection.execute(
        """
        SELECT id
        FROM campaign_component_items
        WHERE component_id = ?
        ORDER BY display_order ASC, id ASC;
        """,
        (component_id,),
    ).fetchall()
    for index, item in enumerate(items, start=1):
        connection.execute(
            """
            UPDATE campaign_component_items
            SET display_order = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?;
            """,
            (index, item["id"]),
        )


def apply_chat_command(
    connection: Any,
    campaign_id: int,
    command: ParsedCommand,
    session_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    campaign = connection.execute(
        """
        SELECT id, business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date
        FROM campaigns
        WHERE id = ?;
        """,
        (campaign_id,),
    ).fetchone()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if command.target == "clarify":
        return {"target": "clarify", "message": command.value}

    if command.target == "campaign":
        if command.field not in CAMPAIGN_FIELDS:
            raise HTTPException(status_code=400, detail="Unsupported campaign field")

        value: str | None = command.value
        if command.field in {"title", "objective"}:
            value = value.strip()
            if value == "":
                raise HTTPException(status_code=400, detail=f"{command.field} cannot be empty")

        if command.field == "status":
            normalized = command.value.lower().strip()
            if normalized not in CAMPAIGN_STATUS_VALUES:
                raise HTTPException(status_code=400, detail="Unsupported campaign status")
            value = normalized

        if command.field in {"start_date", "end_date"}:
            _parse_iso_date(command.value, command.field)

        connection.execute(
            f"UPDATE campaigns SET {command.field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (value, campaign_id),
        )
        updated = connection.execute(
            """
            SELECT id, business_id, campaign_name, campaign_key, title, objective, footnote_text, status, start_date, end_date
            FROM campaigns
            WHERE id = ?;
            """,
            (campaign_id,),
        ).fetchone()
        if updated is None:
            raise HTTPException(status_code=500, detail="Campaign update failed")

        return {"target": "campaign", "field": command.field, "campaign": _campaign_payload(updated)}

    if command.target == "offer":
        if command.offer_id is None:
            raise HTTPException(status_code=400, detail="Offer id is required")
        if command.field not in OFFER_FIELDS:
            raise HTTPException(status_code=400, detail="Unsupported offer field")

        offer = connection.execute(
            """
            SELECT id, campaign_id, offer_name, offer_type, offer_value, start_date, end_date, terms_text
            FROM campaign_offers
            WHERE id = ? AND campaign_id = ?;
            """,
            (command.offer_id, campaign_id),
        ).fetchone()
        if offer is None:
            raise HTTPException(status_code=404, detail="Offer not found")

        value = command.value
        if command.field in {"offer_value", "terms_text"}:
            value = value.strip()
            if value == "":
                raise HTTPException(status_code=400, detail=f"{command.field} cannot be empty")

        if command.field in {"start_date", "end_date"}:
            _parse_iso_date(command.value, command.field)

        next_start = offer["start_date"]
        next_end = offer["end_date"]
        if command.field == "start_date":
            next_start = command.value
        if command.field == "end_date":
            next_end = command.value

        if next_start and next_end:
            start_date = _parse_iso_date(next_start, "start_date")
            end_date = _parse_iso_date(next_end, "end_date")
            if start_date > end_date:
                raise HTTPException(status_code=400, detail="Offer start_date cannot be after end_date")

            siblings = connection.execute(
                """
                SELECT id, start_date, end_date
                FROM campaign_offers
                WHERE campaign_id = ? AND id != ? AND start_date IS NOT NULL AND end_date IS NOT NULL;
                """,
                (campaign_id, command.offer_id),
            ).fetchall()
            for sibling in siblings:
                sibling_start = _parse_iso_date(sibling["start_date"], "start_date")
                sibling_end = _parse_iso_date(sibling["end_date"], "end_date")
                if _offers_overlap(start_date, end_date, sibling_start, sibling_end):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "Offer date window overlaps with an existing offer",
                            "existing_offer_id": sibling["id"],
                        },
                    )

        connection.execute(
            f"UPDATE campaign_offers SET {command.field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (value, command.offer_id),
        )
        updated_offer = connection.execute(
            """
            SELECT id, campaign_id, offer_name, offer_type, offer_value, start_date, end_date, terms_text
            FROM campaign_offers
            WHERE id = ?;
            """,
            (command.offer_id,),
        ).fetchone()
        if updated_offer is None:
            raise HTTPException(status_code=500, detail="Offer update failed")

        return {
            "target": "offer",
            "field": command.field,
            "offer": {
                "id": updated_offer["id"],
                "campaign_id": updated_offer["campaign_id"],
                "offer_name": updated_offer["offer_name"],
                "offer_type": updated_offer["offer_type"],
                "offer_value": updated_offer["offer_value"],
                "start_date": updated_offer["start_date"],
                "end_date": updated_offer["end_date"],
                "terms_text": updated_offer["terms_text"],
            },
        }

    if command.target == "brand":
        if command.field not in BRAND_FIELDS:
            raise HTTPException(status_code=400, detail="Unsupported brand field")

        connection.execute(
            f"""
            INSERT INTO brand_themes (business_id, name, {command.field})
            VALUES (?, 'default', ?)
            ON CONFLICT (business_id, name)
            DO UPDATE SET {command.field} = excluded.{command.field}, updated_at = CURRENT_TIMESTAMP;
            """,
            (campaign["business_id"], command.value.strip()),
        )
        theme = connection.execute(
            """
            SELECT id, business_id, name, primary_color, secondary_color, accent_color, font_family, logo_path
            FROM brand_themes
            WHERE business_id = ? AND name = 'default';
            """,
            (campaign["business_id"],),
        ).fetchone()
        if theme is None:
            raise HTTPException(status_code=500, detail="Brand theme update failed")

        return {
            "target": "brand",
            "field": command.field,
            "brand_theme": {
                "id": theme["id"],
                "business_id": theme["business_id"],
                "name": theme["name"],
                "primary_color": theme["primary_color"],
                "secondary_color": theme["secondary_color"],
                "accent_color": theme["accent_color"],
                "font_family": theme["font_family"],
                "logo_path": theme["logo_path"],
            },
        }

    if command.target == "business":
        if command.field not in BUSINESS_FIELDS:
            raise HTTPException(status_code=400, detail="Unsupported business field")

        business = _load_business(connection, campaign["business_id"])
        if business is None:
            raise HTTPException(status_code=404, detail="Business not found")

        value = command.value.strip()
        if command.field in {"legal_name", "display_name", "timezone"}:
            if value == "":
                raise HTTPException(status_code=400, detail=f"{command.field} cannot be empty")
            try:
                connection.execute(
                    f"UPDATE businesses SET {command.field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                    (value, campaign["business_id"]),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="Business update conflicts with existing data") from exc
        elif command.field == "is_active":
            connection.execute(
                "UPDATE businesses SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                (1 if _parse_boolean_value(value, command.field) else 0, campaign["business_id"]),
            )
        elif command.field == "phone":
            connection.execute(
                "DELETE FROM business_contacts WHERE business_id = ? AND contact_type = 'phone';",
                (campaign["business_id"],),
            )
            connection.execute(
                """
                INSERT INTO business_contacts (business_id, contact_type, contact_value, is_primary)
                VALUES (?, 'phone', ?, 1);
                """,
                (campaign["business_id"], value),
            )
        elif command.field in {"address_line1", "address_line2", "city", "state", "postal_code", "country"}:
            current_line1 = (business["address_line1"] or "").strip()
            current_city = (business["city"] or "").strip()
            current_state = (business["state"] or "").strip()
            current_postal = (business["postal_code"] or "").strip()
            current_line2 = (business["address_line2"] or "").strip()
            current_country = (business["country"] or "US").strip() or "US"

            next_line1 = value if command.field == "address_line1" else current_line1
            next_line2 = value if command.field == "address_line2" else current_line2
            next_city = value if command.field == "city" else current_city
            next_state = value if command.field == "state" else current_state
            next_postal = value if command.field == "postal_code" else current_postal
            next_country = (value if command.field == "country" else current_country) or "US"

            required = (next_line1, next_city, next_state, next_postal)
            has_any = any((next_line1, next_line2, next_city, next_state, next_postal))
            if has_any and not all(required):
                raise HTTPException(
                    status_code=400,
                    detail="Address requires address_line1, city, state, and postal_code",
                )

            connection.execute(
                "DELETE FROM business_locations WHERE business_id = ?;",
                (campaign["business_id"],),
            )
            if has_any:
                connection.execute(
                    """
                    INSERT INTO business_locations (
                        business_id, line1, line2, city, state, postal_code, country
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        campaign["business_id"],
                        next_line1,
                        next_line2 or None,
                        next_city,
                        next_state,
                        next_postal,
                        next_country,
                    ),
                )
        else:
            raise HTTPException(status_code=400, detail="Unsupported business field")

        updated_business = _load_business(connection, campaign["business_id"])
        if updated_business is None:
            raise HTTPException(status_code=500, detail="Business update failed")

        return {
            "target": "business",
            "field": command.field,
            "business": _business_payload(updated_business),
        }

    if command.target == "template_override":
        if command.field not in TEMPLATE_OVERRIDE_FIELDS:
            raise HTTPException(status_code=400, detail="Unsupported template override field")

        binding = connection.execute(
            """
            SELECT id, override_values_json
            FROM campaign_template_bindings
            WHERE campaign_id = ? AND is_active = 1
            ORDER BY id DESC
            LIMIT 1;
            """,
            (campaign_id,),
        ).fetchone()
        if binding is None:
            raise HTTPException(status_code=404, detail="Active template binding not found")

        try:
            override_values = json.loads(binding["override_values_json"] or "{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail="Template override values are not valid JSON") from exc
        if not isinstance(override_values, dict):
            raise HTTPException(status_code=500, detail="Template override values must be a JSON object")

        override_values[command.field] = _coerce_template_override_value(command.field, command.value)
        connection.execute(
            """
            UPDATE campaign_template_bindings
            SET override_values_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?;
            """,
            (json.dumps(override_values, sort_keys=True), binding["id"]),
        )
        return {
            "target": "template_override",
            "field": command.field,
            "template_binding_id": binding["id"],
            "override_values": override_values,
        }

    if command.target == "component":
        if command.component_ref is None:
            raise HTTPException(status_code=400, detail="Component reference is required")

        value = command.value.strip()
        # Some fields are required and cannot be cleared.
        required_fields = {"component_key", "display_title", "component_kind"}
        if command.field in required_fields and value == "":
            raise HTTPException(status_code=400, detail=f"component {command.field} cannot be empty")

        if command.component_ref == "__all__":
            if command.field == "delete":
                raise HTTPException(status_code=400, detail="Deleting all components is not supported in one command")
            if command.field == "component_key":
                raise HTTPException(status_code=400, detail="component_key cannot be set for all components at once")
            if command.field not in COMPONENT_FIELDS:
                raise HTTPException(status_code=400, detail="Unsupported component field")

            if command.field == "component_kind":
                render_region, render_mode = _COMPONENT_RENDER_DEFAULTS.get(value, (None, None))
                connection.execute(
                    """
                    UPDATE campaign_components
                    SET component_kind = ?, render_region = ?, render_mode = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE campaign_id = ?;
                    """,
                    (value, render_region, render_mode, campaign_id),
                )
            else:
                connection.execute(
                    f"UPDATE campaign_components SET {command.field} = ?, updated_at = CURRENT_TIMESTAMP WHERE campaign_id = ?;",
                    (value, campaign_id),
                )
            count_row = connection.execute(
                "SELECT COUNT(*) AS component_count FROM campaign_components WHERE campaign_id = ?;",
                (campaign_id,),
            ).fetchone()
            return {
                "target": "component",
                "field": command.field,
                "updated_count": int(count_row["component_count"]) if count_row is not None else 0,
                "scope": "all_components",
            }

        component = resolve_component(connection, campaign_id, command.component_ref)
        if component is None:
            raise HTTPException(status_code=404, detail="Component not found")

        if command.field == "delete":
            connection.execute("DELETE FROM campaign_components WHERE id = ?;", (component["id"],))
            return {
                "target": "component",
                "field": "delete",
                "deleted": True,
                "component": {
                    "id": component["id"],
                    "campaign_id": component["campaign_id"],
                    "component_key": component["component_key"],
                    "component_kind": component["component_kind"],
                    "display_title": component["display_title"],
                    "background_color": component["background_color"],
                    "header_accent_color": component["header_accent_color"],
                    "footnote_text": component["footnote_text"],
                    "subtitle": component["subtitle"],
                    "description_text": component["description_text"],
                    "display_order": component["display_order"],
                },
            }
        if command.field == "component_key":
            normalized_key = _normalize_component_key(value)
            if normalized_key == "":
                raise HTTPException(status_code=400, detail="component_key must contain letters or numbers")
            try:
                connection.execute(
                    """
                    UPDATE campaign_components
                    SET component_key = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?;
                    """,
                    (normalized_key, component["id"]),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="component_key already exists for this campaign") from exc
        elif command.field in COMPONENT_FIELDS:
            if command.field == "component_kind":
                render_region, render_mode = _COMPONENT_RENDER_DEFAULTS.get(value, (None, None))
                connection.execute(
                    """
                    UPDATE campaign_components
                    SET component_kind = ?, render_region = ?, render_mode = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE campaign_id = ?;
                    """,
                    (value, render_region, render_mode, component["id"]),
                )
            else:
                connection.execute(
                    f"UPDATE campaign_components SET {command.field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                    (value, component["id"]),
                )
        else:
            raise HTTPException(status_code=400, detail="Unsupported component field")
        updated_component = connection.execute(
            """
            SELECT id, campaign_id, component_key, component_kind, display_title, background_color, header_accent_color, footnote_text, subtitle, description_text, display_order
            FROM campaign_components
            WHERE id = ?;
            """,
            (component["id"],),
        ).fetchone()
        if updated_component is None:
            raise HTTPException(status_code=500, detail="Component update failed")

        return {
            "target": "component",
            "field": command.field,
            "component": {
                "id": updated_component["id"],
                "campaign_id": updated_component["campaign_id"],
                "component_key": updated_component["component_key"],
                "component_kind": updated_component["component_kind"],
                "display_title": updated_component["display_title"],
                "background_color": updated_component["background_color"],
                "header_accent_color": updated_component["header_accent_color"],
                "footnote_text": updated_component["footnote_text"],
                "subtitle": updated_component["subtitle"],
                "description_text": updated_component["description_text"],
                "display_order": updated_component["display_order"],
            },
        }

    if command.target == "component_item":
        if command.item_ref is None and command.field != "add":
            raise HTTPException(status_code=400, detail="Item reference is required")
        if command.field not in {"clone", "delete", "add"} and command.field not in COMPONENT_ITEM_FIELDS:
            raise HTTPException(status_code=400, detail="Unsupported component item field")

        component_ref = command.component_ref
        if component_ref is None and session_context is not None:
            component_ref = session_context.get("active_component_ref")
        if component_ref is None:
            return {
                "target": "clarify",
                "message": "Please tell me which component you are working on first, for example: 'I am working on the main-street-appreciation component'.",
            }

        value = command.value.strip()
        if command.field not in {"clone", "delete", "add"} and value == "":
            raise HTTPException(status_code=400, detail=f"component item {command.field} cannot be empty")

        component = resolve_component(connection, campaign_id, component_ref)
        if component is None:
            raise HTTPException(status_code=404, detail="Component not found")

        items = connection.execute(
            """
            SELECT id, component_id, item_name, item_kind, duration_label, item_value, background_color, description_text, terms_text, display_order
            FROM campaign_component_items
            WHERE component_id = ?
            ORDER BY display_order ASC, id ASC;
            """,
            (component["id"],),
        ).fetchall()

        if command.item_ref == "__all__":
            if command.field in {"clone", "delete", "add"}:
                raise HTTPException(status_code=400, detail=f"Bulk '{command.field}' for all items is not supported")

            connection.execute(
                f"UPDATE campaign_component_items SET {command.field} = ?, updated_at = CURRENT_TIMESTAMP WHERE component_id = ?;",
                (value, component["id"]),
            )
            count_row = connection.execute(
                "SELECT COUNT(*) AS item_count FROM campaign_component_items WHERE component_id = ?;",
                (component["id"],),
            ).fetchone()
            return {
                "target": "component_item",
                "field": command.field,
                "deleted": False,
                "updated_count": int(count_row["item_count"]) if count_row is not None else 0,
                "scope": "all_items",
                "component": {
                    "id": component["id"],
                    "campaign_id": component["campaign_id"],
                    "component_key": component["component_key"],
                    "component_kind": component["component_kind"],
                    "display_title": component["display_title"],
                    "background_color": component["background_color"],
                    "display_order": component["display_order"],
                },
            }

        item = None
        if command.item_ref:
            item = _find_component_item(items, command.item_ref)
            if item is None:
                raise HTTPException(status_code=404, detail="Component item not found")

        if command.field == "add":
            if value == "":
                raise HTTPException(status_code=400, detail="Item name cannot be empty")
            
            # Default values
            item_kind = "service"
            duration_label = None
            item_value = ""
            background_color = None
            description_text = None
            terms_text = None

            # If cloning (item_ref is source)
            if item:
                item_kind = item["item_kind"]
                duration_label = item["duration_label"]
                item_value = item["item_value"]
                background_color = item["background_color"]
                description_text = item["description_text"]
                terms_text = item["terms_text"]

            # Insertion position
            insert_position = None
            if command.secondary_item_ref and command.tertiary_item_ref:
                relative_item = _find_component_item(items, command.secondary_item_ref)
                if relative_item is None:
                    raise HTTPException(status_code=404, detail="Relative positioning item not found")
                
                if command.tertiary_item_ref.lower() == "before":
                    insert_position = relative_item["display_order"]
                else:  # "after"
                    insert_position = relative_item["display_order"] + 1
            else:
                # Add to end
                max_order = connection.execute(
                    "SELECT MAX(display_order) FROM campaign_component_items WHERE component_id = ?;",
                    (component["id"],),
                ).fetchone()[0] or 0
                insert_position = max_order + 1

            # Shift
            connection.execute(
                """
                UPDATE campaign_component_items
                SET display_order = display_order + 1, updated_at = CURRENT_TIMESTAMP
                WHERE component_id = ? AND display_order >= ?;
                """,
                (component["id"], insert_position),
            )
            
            # Insert
            inserted_row = connection.execute(
                """
                INSERT INTO campaign_component_items (
                    component_id, item_name, item_kind, duration_label, item_value, background_color, description_text, terms_text, display_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id, component_id, item_name, item_kind, duration_label, item_value, background_color, description_text, terms_text, display_order;
                """,
                (
                    component["id"],
                    value,
                    item_kind,
                    duration_label,
                    item_value,
                    background_color,
                    description_text,
                    terms_text,
                    insert_position,
                ),
            ).fetchone()
            
            if inserted_row is None:
                raise HTTPException(status_code=500, detail="Component item add failed")
            
            _resequence_component_items(connection, component["id"])
            updated_item = inserted_row

        elif command.field == "clone":
            # (Keep existing clone logic for backward compatibility or refactor to use 'add')
            insert_before_ref = command.tertiary_item_ref
            if insert_before_ref is None:
                raise HTTPException(status_code=400, detail="A target item to insert before is required")
            if value == "":
                raise HTTPException(status_code=400, detail="Cloned item name cannot be empty")

            insert_before_item = _find_component_item(items, insert_before_ref)
            if insert_before_item is None:
                raise HTTPException(status_code=404, detail="Target insertion item not found")

            # This is essentially 'add like X before Y'
            insert_position = insert_before_item["display_order"]
            connection.execute(
                """
                UPDATE campaign_component_items
                SET display_order = display_order + 1, updated_at = CURRENT_TIMESTAMP
                WHERE component_id = ? AND display_order >= ?;
                """,
                (component["id"], insert_position),
            )
            inserted_row = connection.execute(
                """
                INSERT INTO campaign_component_items (
                    component_id, item_name, item_kind, duration_label, item_value, background_color, description_text, terms_text, display_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id, component_id, item_name, item_kind, duration_label, item_value, background_color, description_text, terms_text, display_order;
                """,
                (
                    component["id"],
                    value,
                    item["item_kind"],
                    item["duration_label"],
                    item["item_value"],
                    item["background_color"],
                    item["description_text"],
                    item["terms_text"],
                    insert_position,
                ),
            ).fetchone()
            if inserted_row is None:
                raise HTTPException(status_code=500, detail="Component item clone failed")
            _resequence_component_items(connection, component["id"])
            updated_item = inserted_row

        elif command.field == "delete":
            if item is None:
                raise HTTPException(status_code=400, detail="Item reference is required for delete")
            deleted_item = {
                "id": item["id"],
                "component_id": item["component_id"],
                "item_name": item["item_name"],
                "item_kind": item["item_kind"],
                "duration_label": item["duration_label"],
                "item_value": item["item_value"],
                "background_color": item["background_color"],
                "description_text": item["description_text"],
                "terms_text": item["terms_text"],
                "display_order": item["display_order"],
            }
            connection.execute(
                "DELETE FROM campaign_component_items WHERE id = ?;",
                (item["id"],),
            )
            _resequence_component_items(connection, component["id"])
            updated_item = deleted_item
        else:
            if item is None:
                raise HTTPException(status_code=400, detail="Item reference is required for update")
            connection.execute(
                f"UPDATE campaign_component_items SET {command.field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                (value, item["id"]),
            )
            updated_item = connection.execute(
                """
                SELECT id, component_id, item_name, item_kind, duration_label, item_value, background_color, description_text, terms_text, display_order
                FROM campaign_component_items
                WHERE id = ?;
                """,
                (item["id"],),
            ).fetchone()
            if updated_item is None:
                raise HTTPException(status_code=500, detail="Component item update failed")

        return {
            "target": "component_item",
            "field": command.field,
            "deleted": command.field == "delete",
            "component": {
                "id": component["id"],
                "campaign_id": component["campaign_id"],
                "component_key": component["component_key"],
                "component_kind": component["component_kind"],
                "display_title": component["display_title"],
                "background_color": component["background_color"],
                "display_order": component["display_order"],
            },
            "item": {
                "id": updated_item["id"],
                "component_id": updated_item["component_id"],
                "item_name": updated_item["item_name"],
                "item_kind": updated_item["item_kind"],
                "duration_label": updated_item["duration_label"],
                "item_value": updated_item["item_value"],
                "background_color": updated_item["background_color"],
                "description_text": updated_item["description_text"],
                "terms_text": updated_item["terms_text"],
                "display_order": updated_item["display_order"],
            },
        }

    raise HTTPException(status_code=400, detail="Unsupported command target")
