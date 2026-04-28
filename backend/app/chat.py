from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
import sqlite3
import uuid
from typing import Any, Literal

from fastapi import HTTPException


CAMPAIGN_STATUS_VALUES = {"draft", "active", "paused", "completed", "archived"}
CAMPAIGN_FIELDS = {"title", "objective", "status", "start_date", "end_date"}
OFFER_FIELDS = {"offer_value", "start_date", "end_date", "terms_text"}
BRAND_FIELDS = {"primary_color", "secondary_color", "accent_color", "font_family", "logo_path"}

# Matches: "clone <source> [and] rename [it] to <new_name> [for <business>]"
# Also accepts more verbose natural-language phrasings ("cloning the X ... renaming it to Y").
_CLONE_PATTERN = re.compile(
    r"clon(?:e|ing)\s+(?:the\s+)?(?P<source>[A-Za-z0-9._-]+)"
    r"(?:.*?renam(?:e|ing)(?:\s+it)?\s+to\s+(?P<new_name>[A-Za-z0-9._-]+))"
    r"(?:.*?(?:for\s+(?P<business>[A-Za-z0-9._-]+)))?",
    re.IGNORECASE | re.DOTALL,
)

CAMPAIGN_PATTERN = re.compile(r"^set\s+(title|objective|status|start_date|end_date)\s+to\s+(.+)$", re.IGNORECASE)
OFFER_PATTERN = re.compile(
    r"^set\s+offer\s+(\d+)\s+(offer_value|start_date|end_date|terms_text)\s+to\s+(.+)$",
    re.IGNORECASE,
)
BRAND_PATTERN = re.compile(
    r"^set\s+brand\s+(primary_color|secondary_color|accent_color|font_family|logo_path)\s+to\s+(.+)$",
    re.IGNORECASE,
)
COMPONENT_SET_PATTERN = re.compile(
    r"^set\s+component\s+(.+?)\s+(name|title|display_title|component_key|key)\s+to\s+(.+)$",
    re.IGNORECASE,
)
COMPONENT_CHANGE_NAME_PATTERN = re.compile(
    r"^change\s+the\s+name\s+of\s+(?:the\s+)?(.+?)\s+component\s+to\s+(.+)$",
    re.IGNORECASE,
)
COMPONENT_CHANGE_NAME_INCOMPLETE_PATTERN = re.compile(
    r"^change\s+the\s+name\s+of\s+(?:the\s+)?(.+?)\s+component\s*[.!?]?$",
    re.IGNORECASE,
)
COMPONENT_CHANGE_KEY_FIELD_PATTERN = re.compile(
    r"^change\s+(?:the\s+)?component[-_\s]?key\s+field\s+of\s+(?:the\s+)?(.+?)\s+component\s+to\s+(.+)$",
    re.IGNORECASE,
)
COMPONENT_CHANGE_KEY_FIELD_INCOMPLETE_PATTERN = re.compile(
    r"^change\s+(?:the\s+)?component[-_\s]?key\s+field\s+of\s+(?:the\s+)?(.+?)\s+component\s*[.!?]?$",
    re.IGNORECASE,
)
COMPONENT_RENAME_PATTERN = re.compile(
    r"^rename\s+(?:the\s+)?component\s+(.+?)\s+to\s+(.+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedCommand:
    target: Literal["campaign", "offer", "brand", "component", "clarify"]
    field: str
    value: str
    offer_id: int | None = None
    component_ref: str | None = None


@dataclass(frozen=True)
class ParsedCloneCommand:
    source_campaign_name: str  # slug of the campaign to clone
    new_campaign_name: str     # slug for the new campaign
    business_name: str | None  # optional business slug hint from the message


class ChatSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, list[dict[str, str]]] = {}

    def create(self) -> str:
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = []
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


def parse_chat_command(message: str) -> ParsedCommand:
    text = message.strip()

    campaign_match = CAMPAIGN_PATTERN.match(text)
    if campaign_match:
        field = campaign_match.group(1).lower()
        value = campaign_match.group(2).strip()
        return ParsedCommand(target="campaign", field=field, value=value)

    offer_match = OFFER_PATTERN.match(text)
    if offer_match:
        offer_id = int(offer_match.group(1))
        field = offer_match.group(2).lower()
        value = offer_match.group(3).strip()
        return ParsedCommand(target="offer", field=field, value=value, offer_id=offer_id)

    brand_match = BRAND_PATTERN.match(text)
    if brand_match:
        field = brand_match.group(1).lower()
        value = brand_match.group(2).strip()
        return ParsedCommand(target="brand", field=field, value=value)

    component_set_match = COMPONENT_SET_PATTERN.match(text)
    if component_set_match:
        component_ref = component_set_match.group(1).strip().strip("\"'")
        field_token = component_set_match.group(2).lower().strip()
        value = component_set_match.group(3).strip()
        field = "component_key" if field_token in {"name", "component_key", "key"} else "display_title"
        return ParsedCommand(target="component", field=field, value=value, component_ref=component_ref)

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

    raise HTTPException(
        status_code=400,
        detail=(
            "Unsupported edit command. Use one of: "
            "'set <campaign_field> to <value>', "
            "'set offer <offer_id> <offer_field> to <value>', "
            "'set brand <brand_field> to <value>', "
            "or 'change the component-key field of <component> component to <new_component_key>'."
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
        "status": row["status"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
    }


def _normalize_component_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower().strip())
    normalized = normalized.strip("-")
    return normalized


def apply_chat_command(connection: Any, campaign_id: int, command: ParsedCommand) -> dict[str, Any]:
    campaign = connection.execute(
        """
        SELECT id, business_id, campaign_name, campaign_key, title, objective, status, start_date, end_date
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
            SELECT id, business_id, campaign_name, campaign_key, title, objective, status, start_date, end_date
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

    if command.target == "component":
        if command.component_ref is None:
            raise HTTPException(status_code=400, detail="Component reference is required")

        value = command.value.strip()
        if value == "":
            raise HTTPException(status_code=400, detail=f"component {command.field} cannot be empty")

        component = connection.execute(
            """
            SELECT id, campaign_id, component_key, component_kind, display_title, footnote_text, subtitle, description_text, display_order
            FROM campaign_components
            WHERE campaign_id = ?
              AND (LOWER(component_key) = LOWER(?) OR LOWER(display_title) = LOWER(?))
            ORDER BY id ASC
            LIMIT 1;
            """,
            (campaign_id, command.component_ref, command.component_ref),
        ).fetchone()
        if component is None:
            raise HTTPException(status_code=404, detail="Component not found")

        if command.field == "display_title":
            connection.execute(
                """
                UPDATE campaign_components
                SET display_title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
                """,
                (value, component["id"]),
            )
        elif command.field == "component_key":
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
        else:
            raise HTTPException(status_code=400, detail="Unsupported component field")
        updated_component = connection.execute(
            """
            SELECT id, campaign_id, component_key, component_kind, display_title, footnote_text, subtitle, description_text, display_order
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
                "footnote_text": updated_component["footnote_text"],
                "subtitle": updated_component["subtitle"],
                "description_text": updated_component["description_text"],
                "display_order": updated_component["display_order"],
            },
        }

    raise HTTPException(status_code=400, detail="Unsupported command target")
