"""Tests for backend/app/llm.py — LLM translate-and-apply pipeline.

All LLM calls are mocked; no real API calls are made.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import AppConfig
from app.db import connect_database, initialize_database
from app.llm import (
    COMPONENT_EDITABLE_FIELDS,
    build_system_prompt,
    dispatch_llm_action,
    parse_llm_response,
    translate_and_apply,
)
from .conftest import make_test_client, write_isolated_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path) -> AppConfig:
    db_path = tmp_path / "db" / "test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        config_path=tmp_path / ".config",
        database_path=db_path,
        output_dir=tmp_path / "output",
        data_dir=tmp_path / "data",
        images_per_page=None,
        using_test_paths=False,
        commit_on_save=False,
        git_repo_path=None,
        git_user_name=None,
        git_user_email=None,
        openrouter_api_key="test-key",
    )


def _make_db(config: AppConfig) -> sqlite3.Connection:
    initialize_database(config)
    conn = sqlite3.connect(str(config.database_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _seed(conn: sqlite3.Connection) -> tuple[int, int]:
    """Insert one business + one campaign with one component and one offer."""
    cursor = conn.execute(
        "INSERT INTO businesses (legal_name, display_name, timezone) VALUES (?,?,?);",
        ("Acme LLC", "Acme", "America/New_York"),
    )
    business_id = cursor.lastrowid

    conn.execute(
        """INSERT INTO brand_themes (business_id, name, primary_color)
           VALUES (?, 'default', '#FF0000');""",
        (business_id,),
    )

    cursor = conn.execute(
        """INSERT INTO campaigns (business_id, campaign_name, title, objective, status)
           VALUES (?,?,?,?,?);""",
        (business_id, "summer-sale", "Summer Sale", "Drive traffic", "draft"),
    )
    campaign_id = cursor.lastrowid

    conn.execute(
        """INSERT INTO campaign_components
           (campaign_id, component_key, component_kind, display_title, display_order)
           VALUES (?,?,?,?,?);""",
        (campaign_id, "featured", "featured-offers", "Featured Offers", 1),
    )

    conn.execute(
        """INSERT INTO campaign_offers
           (campaign_id, offer_name, offer_type, offer_value)
           VALUES (?,?,?,?);""",
        (campaign_id, "Main Offer", "discount", "20%"),
    )

    conn.commit()
    return business_id, campaign_id


# ---------------------------------------------------------------------------
# parse_llm_response
# ---------------------------------------------------------------------------

class TestParseLlmResponse:
    def test_plain_json(self):
        obj = parse_llm_response('{"action": "clarify", "message": "Which field?"}')
        assert obj["action"] == "clarify"

    def test_strips_markdown_fences(self):
        text = '```json\n{"action": "set_campaign_field", "field": "title", "value": "New"}\n```'
        obj = parse_llm_response(text)
        assert obj["action"] == "set_campaign_field"

    def test_extracts_json_from_prose(self):
        text = 'Sure! Here is the command: {"action": "clarify", "message": "OK"} Hope that helps.'
        obj = parse_llm_response(text)
        assert obj["action"] == "clarify"

    def test_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match="non-JSON"):
            parse_llm_response("I cannot help with that.")

    def test_raises_on_missing_action(self):
        with pytest.raises(ValueError, match="missing 'action'"):
            parse_llm_response('{"field": "title"}')


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_contains_campaign_fields(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        prompt = build_system_prompt(conn, campaign_id)
        assert "summer-sale" in prompt
        assert "Summer Sale" in prompt
        assert "featured" in prompt
        assert "featured-offers" in prompt
        assert "title" in prompt
        assert "set_campaign_field" in prompt
        conn.close()

    def test_contains_brand_theme(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        prompt = build_system_prompt(conn, campaign_id)
        assert "#FF0000" in prompt
        conn.close()

    def test_contains_offer(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        prompt = build_system_prompt(conn, campaign_id)
        assert "Main Offer" in prompt
        assert "20%" in prompt
        conn.close()

    def test_raises_for_unknown_campaign(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        with pytest.raises(ValueError, match="not found"):
            build_system_prompt(conn, 9999)
        conn.close()


# ---------------------------------------------------------------------------
# dispatch_llm_action
# ---------------------------------------------------------------------------

class TestDispatchLlmAction:
    def test_set_campaign_field(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        result = dispatch_llm_action(
            conn, campaign_id, {"action": "set_campaign_field", "field": "title", "value": "New Title"}
        )
        assert result["target"] == "campaign"
        assert result["field"] == "title"
        row = conn.execute("SELECT title FROM campaigns WHERE id = ?;", (campaign_id,)).fetchone()
        assert row["title"] == "New Title"
        conn.close()

    def test_set_brand_field(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        result = dispatch_llm_action(
            conn, campaign_id, {"action": "set_brand_field", "field": "primary_color", "value": "#AABBCC"}
        )
        assert result["target"] == "brand"
        conn.close()

    def test_set_component_field(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        result = dispatch_llm_action(
            conn,
            campaign_id,
            {
                "action": "set_component_field",
                "component_key": "featured",
                "field": "display_title",
                "value": "Spring Highlights",
            },
        )
        assert result["target"] == "component"
        assert result["field"] == "display_title"
        assert result["component"]["display_title"] == "Spring Highlights"
        conn.close()

    def test_set_component_field_unknown_component(self, tmp_path):
        from fastapi import HTTPException

        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        with pytest.raises(HTTPException, match="not found"):
            dispatch_llm_action(
                conn,
                campaign_id,
                {
                    "action": "set_component_field",
                    "component_key": "nonexistent",
                    "field": "display_title",
                    "value": "X",
                },
            )
        conn.close()

    def test_clarify_returns_message(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        result = dispatch_llm_action(
            conn, campaign_id, {"action": "clarify", "message": "Which component did you mean?"}
        )
        assert result["target"] == "clarify"
        assert "component" in result["message"]
        conn.close()

    def test_unknown_action_raises(self, tmp_path):
        from fastapi import HTTPException

        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        with pytest.raises(HTTPException, match="unknown action"):
            dispatch_llm_action(conn, campaign_id, {"action": "explode"})
        conn.close()

    def test_rejects_unknown_campaign_field(self, tmp_path):
        from fastapi import HTTPException

        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        with pytest.raises(HTTPException, match="unknown campaign field"):
            dispatch_llm_action(
                conn, campaign_id, {"action": "set_campaign_field", "field": "bad_field", "value": "x"}
            )
        conn.close()

    def test_rejects_unknown_component_field(self, tmp_path):
        from fastapi import HTTPException

        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        with pytest.raises(HTTPException, match="unknown component field"):
            dispatch_llm_action(
                conn,
                campaign_id,
                {
                    "action": "set_component_field",
                    "component_key": "featured",
                    "field": "bad_field",
                    "value": "x",
                },
            )
        conn.close()


# ---------------------------------------------------------------------------
# translate_and_apply (end-to-end with mocked LLM)
# ---------------------------------------------------------------------------

class TestTranslateAndApply:
    def _llm_response(self, obj: dict) -> str:
        return json.dumps(obj)

    def test_applies_campaign_field_via_llm(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        llm_json = self._llm_response(
            {"action": "set_campaign_field", "field": "title", "value": "Summer Blowout"}
        )
        with patch("app.llm.call_llm", return_value=llm_json):
            result = translate_and_apply(conn, campaign_id, "test-key", "change the title to Summer Blowout")
        assert result["target"] == "campaign"
        assert result["field"] == "title"
        conn.close()

    def test_applies_component_field_via_llm(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        llm_json = self._llm_response(
            {
                "action": "set_component_field",
                "component_key": "featured",
                "field": "display_title",
                "value": "Main Highlights",
            }
        )
        with patch("app.llm.call_llm", return_value=llm_json):
            result = translate_and_apply(
                conn, campaign_id, "test-key", "rename the featured section to Main Highlights"
            )
        assert result["target"] == "component"
        assert result["component"]["display_title"] == "Main Highlights"
        conn.close()

    def test_clarify_does_not_mutate(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        llm_json = self._llm_response({"action": "clarify", "message": "Which campaign?"})
        with patch("app.llm.call_llm", return_value=llm_json):
            result = translate_and_apply(conn, campaign_id, "test-key", "update something")
        assert result["target"] == "clarify"
        assert result["message"] == "Which campaign?"
        conn.close()

    def test_llm_error_propagates(self, tmp_path):
        config = _make_config(tmp_path)
        conn = _make_db(config)
        _, campaign_id = _seed(conn)
        with patch("app.llm.call_llm", side_effect=RuntimeError("network error")):
            with pytest.raises(RuntimeError, match="network error"):
                translate_and_apply(conn, campaign_id, "test-key", "do something")
        conn.close()


# ---------------------------------------------------------------------------
# Integration: post_chat_message with mocked LLM
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, data_dir: Path, api_key: str | None = None) -> Path:
    return write_isolated_config(
        tmp_path,
        runtime_data_dir=tmp_path / "yaml-data-runtime",
        test_data_dir=data_dir,
        runtime_database_path=tmp_path / "db" / "runtime.db",
        test_database_path=tmp_path / "db" / "test.db",
        commit_on_save=False,
        openrouter_api_key=api_key,
    )


def _seed_via_client(client) -> tuple[int, int]:
    from fastapi.testclient import TestClient

    biz = client.post(
        "/businesses",
        json={"legal_name": "Acme LLC", "display_name": "Acme", "timezone": "America/New_York"},
    ).json()
    camp = client.post(
        f"/businesses/{biz['id']}/campaigns",
        json={"campaign_name": "summer-sale", "title": "Summer Sale"},
    ).json()
    return biz["id"], camp["id"]


class TestChatEndpointWithLlm:
    def test_llm_applies_campaign_field(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        config_path = _write_config(tmp_path, data_dir, api_key="test-key")
        client = make_test_client(monkeypatch, config_path)
        _, campaign_id = _seed_via_client(client)
        session_id = client.post("/chat/sessions").json()["session_id"]

        llm_json = json.dumps({"action": "set_campaign_field", "field": "title", "value": "Fall Blowout"})
        with patch("app.llm.call_llm", return_value=llm_json):
            resp = client.post(
                f"/chat/sessions/{session_id}/messages",
                json={"campaign_id": campaign_id, "message": "change the title to Fall Blowout"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["target"] == "campaign"
        assert body["result"]["field"] == "title"

    def test_llm_clarify_forwarded_to_history(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        config_path = _write_config(tmp_path, data_dir, api_key="test-key")
        client = make_test_client(monkeypatch, config_path)
        _, campaign_id = _seed_via_client(client)
        session_id = client.post("/chat/sessions").json()["session_id"]

        llm_json = json.dumps({"action": "clarify", "message": "Which component did you mean?"})
        with patch("app.llm.call_llm", return_value=llm_json):
            resp = client.post(
                f"/chat/sessions/{session_id}/messages",
                json={"campaign_id": campaign_id, "message": "update that thing"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["target"] == "clarify"
        history_roles = [h["role"] for h in body["history"]]
        assert "assistant" in history_roles

    def test_no_api_key_falls_back_to_regex(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        config_path = _write_config(tmp_path, data_dir, api_key=None)
        client = make_test_client(monkeypatch, config_path)
        _, campaign_id = _seed_via_client(client)
        session_id = client.post("/chat/sessions").json()["session_id"]

        resp = client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"campaign_id": campaign_id, "message": "set title to Regex Title"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["target"] == "campaign"
        assert body["result"]["field"] == "title"
        assert "warning" not in body

    def test_llm_failure_falls_back_to_regex_with_warning(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        config_path = _write_config(tmp_path, data_dir, api_key="test-key")
        client = make_test_client(monkeypatch, config_path)
        _, campaign_id = _seed_via_client(client)
        session_id = client.post("/chat/sessions").json()["session_id"]

        with patch("app.llm.call_llm", side_effect=RuntimeError("network error")):
            resp = client.post(
                f"/chat/sessions/{session_id}/messages",
                json={"campaign_id": campaign_id, "message": "set title to Fallback Title"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["target"] == "campaign"
        assert "warning" in body
