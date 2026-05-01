"""LLM-backed natural language → structured edit command translation.

The LLM (via OpenRouter) acts as a translator only.  It receives a system
prompt that describes the full campaign schema and the current campaign state,
then returns a JSON command object.  All mutations are applied by the existing
server-side handlers in chat.py, never by the LLM directly.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from .models import Campaign

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM action schema
# ---------------------------------------------------------------------------
# The LLM is instructed to respond with a JSON object matching one of these
# shapes.  Unknown actions are treated as clarification requests.

COMPONENT_EDITABLE_FIELDS = {
    "component_key",
    "component_kind",
    "display_title",
    "subtitle",
    "description_text",
    "footnote_text",
}
BUSINESS_EDITABLE_FIELDS = {
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

_ACTIONS = """
Respond ONLY with a JSON object (no markdown fences, no commentary) that
matches exactly one of the following shapes:

1. Set a campaign-level field:
   {"action": "set_campaign_field", "field": "<field>", "value": "<value>"}
    Allowed fields: title, objective, footnote_text, status, start_date, end_date
   Status must be one of: draft, active, paused, completed, archived
   Dates must be YYYY-MM-DD

2. Set a brand theme field:
   {"action": "set_brand_field", "field": "<field>", "value": "<value>"}
   Allowed fields: primary_color, secondary_color, accent_color, font_family, logo_path

3. Set a field on a named component:
   {"action": "set_component_field", "component_key": "<key>", "field": "<field>", "value": "<value>"}
    Allowed fields: component_key, component_kind, display_title, subtitle, description_text, footnote_text

4. Set a field on a campaign offer (use the numeric id from the context):
   {"action": "set_offer_field", "offer_id": <int>, "field": "<field>", "value": "<value>"}
   Allowed fields: offer_value, start_date, end_date, terms_text

5. Set a business profile field for the business that owns the active campaign:
    {"action": "set_business_field", "field": "<field>", "value": "<value>"}
    Allowed fields: legal_name, display_name, timezone, is_active, phone,
    address_line1, address_line2, city, state, postal_code, country

6. Ask the user a clarifying question when the request is ambiguous or
   references something not present in the provided context:
   {"action": "clarify", "message": "<question>"}

Do not invent field names, component keys, or offer ids that are not present
in the provided context.  Do not perform multiple edits in a single response —
ask for one thing at a time.
"""

# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def build_system_prompt(connection: Any, campaign_id: int) -> str:
    """Serialize current business + campaign state into the LLM system prompt."""
    campaign = connection.execute(
        """
        SELECT c.id, c.campaign_name, c.title, c.objective, c.footnote_text,
               c.status, c.start_date, c.end_date,
               b.id AS business_id, b.display_name AS business_name,
               b.legal_name
        FROM campaigns c
        JOIN businesses b ON b.id = c.business_id
        WHERE c.id = ?;
        """,
        (campaign_id,),
    ).fetchone()
    if campaign is None:
        raise ValueError(f"Campaign {campaign_id} not found")

    theme = connection.execute(
        """
        SELECT primary_color, secondary_color, accent_color, font_family, logo_path
        FROM brand_themes
        WHERE business_id = ? AND name = 'default';
        """,
        (campaign["business_id"],),
    ).fetchone()

    components = connection.execute(
        """
        SELECT component_key, component_kind, display_title, subtitle,
               description_text, footnote_text, display_order
        FROM campaign_components
        WHERE campaign_id = ?
        ORDER BY display_order ASC, id ASC;
        """,
        (campaign_id,),
    ).fetchall()

    items_by_component: dict[str, list[dict[str, Any]]] = {}
    for comp in components:
        rows = connection.execute(
            """
            SELECT item_name, item_kind, duration_label, item_value,
                   description_text, terms_text, display_order
            FROM campaign_component_items
            WHERE component_id = (
                SELECT id FROM campaign_components
                WHERE campaign_id = ? AND component_key = ?
            )
            ORDER BY display_order ASC;
            """,
            (campaign_id, comp["component_key"]),
        ).fetchall()
        items_by_component[comp["component_key"]] = [dict(r) for r in rows]

    offers = connection.execute(
        """
        SELECT id, offer_name, offer_type, offer_value, start_date, end_date, terms_text
        FROM campaign_offers
        WHERE campaign_id = ?
        ORDER BY id ASC;
        """,
        (campaign_id,),
    ).fetchall()

    lines: list[str] = [
        "You are a campaign editing assistant for a marketing promotions engine.",
        "Your job is to translate the user's natural-language request into a single",
        "structured JSON edit command.  You never apply edits yourself.",
        "",
        "=== CURRENT CONTEXT ===",
        "",
        f"Business: {campaign['business_name']} ({campaign['legal_name']})",
    ]

    business = connection.execute(
        """
        SELECT b.timezone, b.is_active,
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
        (campaign["business_id"],),
    ).fetchone()

    if business:
        lines += [
            f"  display_name: {campaign['business_name']}",
            f"  legal_name: {campaign['legal_name']}",
            f"  timezone: {business['timezone']}",
            f"  is_active: {bool(business['is_active'])}",
            f"  phone: {business['phone']}",
            f"  address_line1: {business['address_line1']}",
            f"  address_line2: {business['address_line2']}",
            f"  city: {business['city']}",
            f"  state: {business['state']}",
            f"  postal_code: {business['postal_code']}",
            f"  country: {business['country']}",
        ]

    if theme:
        lines += [
            "Brand theme:",
            f"  primary_color: {theme['primary_color']}",
            f"  secondary_color: {theme['secondary_color']}",
            f"  accent_color: {theme['accent_color']}",
            f"  font_family: {theme['font_family']}",
            f"  logo_path: {theme['logo_path']}",
        ]

    lines += [
        "",
        f"Campaign: {campaign['campaign_name']} (id={campaign['id']})",
        f"  title: {campaign['title']}",
        f"  objective: {campaign['objective']}",
        f"  status: {campaign['status']}",
        f"  start_date: {campaign['start_date']}",
        f"  end_date: {campaign['end_date']}",
        f"  footnote_text: {campaign['footnote_text']}",
    ]

    if components:
        lines.append("")
        lines.append("Components (ordered):")
        for comp in components:
            key = comp["component_key"]
            lines.append(f"  [{key}] kind={comp['component_kind']} order={comp['display_order']}")
            lines.append(f"    display_title: {comp['display_title']}")
            lines.append(f"    subtitle: {comp['subtitle']}")
            lines.append(f"    description_text: {comp['description_text']}")
            lines.append(f"    footnote_text: {comp['footnote_text']}")
            for item in items_by_component.get(key, []):
                lines.append(
                    f"    item: {item['item_name']} | {item['item_kind']} | "
                    f"{item['item_value']} | {item['duration_label']}"
                )

    if offers:
        lines.append("")
        lines.append("Offers:")
        for offer in offers:
            lines.append(
                f"  id={offer['id']} name={offer['offer_name']} type={offer['offer_type']} "
                f"value={offer['offer_value']} {offer['start_date']}→{offer['end_date']}"
            )

    lines += ["", "=== INSTRUCTIONS ===", _ACTIONS]
    return "\n".join(lines)


def build_system_prompt_session(db: Session, campaign_id: int) -> str:
    """Serialize current business + campaign state into the LLM system prompt using SQLAlchemy."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise ValueError(f"Campaign {campaign_id} not found")

    business = campaign.business
    theme = next((row for row in business.brand_themes if row.name == "default"), None)
    location = next(iter(sorted(business.locations, key=lambda row: row.id)), None)
    phone = next(
        (
            row.contact_value
            for row in sorted(business.contacts, key=lambda row: (not row.is_primary, row.id))
            if row.contact_type == "phone"
        ),
        None,
    )
    components = sorted(campaign.components, key=lambda row: (row.display_order, row.id))
    offers = sorted(campaign.offers, key=lambda row: row.id)

    lines: list[str] = [
        "You are a campaign editing assistant for a marketing promotions engine.",
        "Your job is to translate the user's natural-language request into a single",
        "structured JSON edit command.  You never apply edits yourself.",
        "",
        "=== CURRENT CONTEXT ===",
        "",
        f"Business: {business.display_name} ({business.legal_name})",
        f"  display_name: {business.display_name}",
        f"  legal_name: {business.legal_name}",
        f"  timezone: {business.timezone}",
        f"  is_active: {bool(business.is_active)}",
        f"  phone: {phone}",
        f"  address_line1: {location.line1 if location else None}",
        f"  address_line2: {location.line2 if location else None}",
        f"  city: {location.city if location else None}",
        f"  state: {location.state if location else None}",
        f"  postal_code: {location.postal_code if location else None}",
        f"  country: {location.country if location else None}",
    ]

    if theme:
        lines += [
            "Brand theme:",
            f"  primary_color: {theme.primary_color}",
            f"  secondary_color: {theme.secondary_color}",
            f"  accent_color: {theme.accent_color}",
            f"  font_family: {theme.font_family}",
            f"  logo_path: {theme.logo_path}",
        ]

    lines += [
        "",
        f"Campaign: {campaign.campaign_name} (id={campaign.id})",
        f"  title: {campaign.title}",
        f"  objective: {campaign.objective}",
        f"  status: {campaign.status}",
        f"  start_date: {campaign.start_date}",
        f"  end_date: {campaign.end_date}",
        f"  footnote_text: {campaign.footnote_text}",
    ]

    if components:
        lines.append("")
        lines.append("Components (ordered):")
        for component in components:
            lines.append(
                f"  [{component.component_key}] kind={component.component_kind} "
                f"order={component.display_order}"
            )
            lines.append(f"    display_title: {component.display_title}")
            lines.append(f"    subtitle: {component.subtitle}")
            lines.append(f"    description_text: {component.description_text}")
            lines.append(f"    footnote_text: {component.footnote_text}")
            for item in sorted(component.items, key=lambda row: (row.display_order, row.id)):
                lines.append(
                    f"    item: {item.item_name} | {item.item_kind} | "
                    f"{item.item_value} | {item.duration_label}"
                )

    if offers:
        lines.append("")
        lines.append("Offers:")
        for offer in offers:
            lines.append(
                f"  id={offer.id} name={offer.offer_name} type={offer.offer_type} "
                f"value={offer.offer_value} {offer.start_date}→{offer.end_date}"
            )

    lines += ["", "=== INSTRUCTIONS ===", _ACTIONS]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def call_llm(api_key: str, system_prompt: str, user_message: str) -> str:
    """Call OpenRouter and return the raw text response."""
    from openai import OpenAI  # deferred import so the module loads without the package in tests

    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        max_tokens=512,
        temperature=0,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def parse_llm_response(text: str) -> dict[str, Any]:
    """Extract and validate the JSON command from the LLM reply.

    Strips markdown code fences if present. Raises ValueError for invalid JSON
    or missing required keys. Unknown actions are returned as-is so the caller
    can decide what to do.
    """
    # Strip markdown fences
    stripped = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()

    # If the LLM wrapped the JSON in prose, find the first {...} block
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        stripped = match.group(0)

    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned non-JSON response: {text!r}") from exc

    if not isinstance(obj, dict):
        raise ValueError(f"LLM response is not a JSON object: {obj!r}")

    action = obj.get("action")
    if not action:
        raise ValueError(f"LLM response missing 'action' key: {obj!r}")

    return obj


# ---------------------------------------------------------------------------
# Command dispatcher: LLM action → ParsedCommand / component update
# ---------------------------------------------------------------------------

def dispatch_llm_action(
    connection: Any,
    campaign_id: int,
    action_obj: dict[str, Any],
) -> dict[str, Any]:
    """Translate a validated LLM action object into a structured edit and apply it.

    Returns the same result dict format as apply_chat_command / component edits,
    or a {"target": "clarify", "message": ...} dict for clarification requests.
    Raises HTTPException for schema violations (propagated to caller).
    """
    from fastapi import HTTPException
    from .chat import (
        ParsedCommand,
        apply_chat_command,
        CAMPAIGN_FIELDS,
        BRAND_FIELDS,
        BUSINESS_FIELDS,
        CAMPAIGN_STATUS_VALUES,
    )

    action = action_obj.get("action", "")

    if action == "clarify":
        message = action_obj.get("message", "")
        return {"target": "clarify", "message": str(message)}

    if action == "set_campaign_field":
        field = str(action_obj.get("field", "")).strip()
        value = str(action_obj.get("value", "")).strip()
        if field not in CAMPAIGN_FIELDS:
            raise HTTPException(status_code=400, detail=f"LLM returned unknown campaign field: {field!r}")
        return apply_chat_command(connection, campaign_id, ParsedCommand(target="campaign", field=field, value=value))

    if action == "set_brand_field":
        field = str(action_obj.get("field", "")).strip()
        value = str(action_obj.get("value", "")).strip()
        if field not in BRAND_FIELDS:
            raise HTTPException(status_code=400, detail=f"LLM returned unknown brand field: {field!r}")
        return apply_chat_command(connection, campaign_id, ParsedCommand(target="brand", field=field, value=value))

    if action == "set_business_field":
        field = str(action_obj.get("field", "")).strip()
        value = str(action_obj.get("value", "")).strip()
        if field not in BUSINESS_FIELDS:
            raise HTTPException(status_code=400, detail=f"LLM returned unknown business field: {field!r}")
        return apply_chat_command(connection, campaign_id, ParsedCommand(target="business", field=field, value=value))

    if action == "set_offer_field":
        from .chat import OFFER_FIELDS
        offer_id_raw = action_obj.get("offer_id")
        try:
            offer_id = int(offer_id_raw)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="LLM returned invalid offer_id") from exc
        field = str(action_obj.get("field", "")).strip()
        value = str(action_obj.get("value", "")).strip()
        if field not in OFFER_FIELDS:
            raise HTTPException(status_code=400, detail=f"LLM returned unknown offer field: {field!r}")
        return apply_chat_command(
            connection, campaign_id, ParsedCommand(target="offer", field=field, value=value, offer_id=offer_id)
        )

    if action == "set_component_field":
        component_key = str(action_obj.get("component_key", "")).strip()
        field = str(action_obj.get("field", "")).strip()
        value = str(action_obj.get("value", "")).strip()
        if not component_key:
            raise HTTPException(status_code=400, detail="LLM response missing component_key")
        if field not in COMPONENT_EDITABLE_FIELDS:
            raise HTTPException(status_code=400, detail=f"LLM returned unknown component field: {field!r}")

        # Validate component exists for this campaign
        comp = connection.execute(
            "SELECT id FROM campaign_components WHERE campaign_id = ? AND component_key = ?;",
            (campaign_id, component_key),
        ).fetchone()
        if comp is None:
            raise HTTPException(
                status_code=404,
                detail=f"Component '{component_key}' not found in campaign {campaign_id}",
            )
        return apply_chat_command(
            connection,
            campaign_id,
            ParsedCommand(target="component", field=field, value=value, component_ref=component_key),
        )

    raise HTTPException(status_code=400, detail=f"LLM returned unknown action: {action!r}")


# ---------------------------------------------------------------------------
# Main entry point used by post_chat_message
# ---------------------------------------------------------------------------

def translate_and_apply(
    connection: Any,
    campaign_id: int,
    api_key: str,
    user_message: str,
) -> dict[str, Any]:
    """Full pipeline: build prompt → call LLM → parse → dispatch → return result."""
    system_prompt = build_system_prompt(connection, campaign_id)
    raw = call_llm(api_key, system_prompt, user_message)
    log.debug("LLM raw response: %r", raw)
    action_obj = parse_llm_response(raw)
    return dispatch_llm_action(connection, campaign_id, action_obj)
