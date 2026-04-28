"""Tests for campaign cloning via chat command and data_sync helper."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from app.chat import ParsedCloneCommand, parse_clone_command
from app.data_sync import clone_campaign_directory
from app.db import connect_database, initialize_database
from .conftest import make_test_client, write_isolated_config


# ---------------------------------------------------------------------------
# parse_clone_command
# ---------------------------------------------------------------------------

def test_parse_clone_natural_language():
    msg = (
        "I want to create a new campaign for merci by cloning the "
        "merci-may-sales2 promotion and renaming it to main-street-appreciation."
    )
    result = parse_clone_command(msg)
    assert result is not None
    assert result.source_campaign_name == "merci-may-sales2"
    assert result.new_campaign_name == "main-street-appreciation"


def test_parse_clone_short_form():
    result = parse_clone_command("clone summer-sale and rename it to fall-clearance")
    assert result is not None
    assert result.source_campaign_name == "summer-sale"
    assert result.new_campaign_name == "fall-clearance"


def test_parse_clone_with_business_hint():
    result = parse_clone_command("clone mothersday rename to fathersday for acme")
    assert result is not None
    assert result.source_campaign_name == "mothersday"
    assert result.new_campaign_name == "fathersday"
    assert result.business_name == "acme"


def test_parse_clone_returns_none_for_unrelated_message():
    assert parse_clone_command("set title to Summer Sale") is None
    assert parse_clone_command("What campaigns do we have?") is None


# ---------------------------------------------------------------------------
# clone_campaign_directory
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    import sqlite3
    from app.config import AppConfig
    db_path = tmp_path / "db" / "test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    output_dir = tmp_path / "output"
    data_dir = tmp_path / "data"
    config = AppConfig(
        config_path=tmp_path / ".config",
        database_path=db_path,
        output_dir=output_dir,
        data_dir=data_dir,
        images_per_page=None,
        using_test_paths=False,
        commit_on_save=False,
        git_repo_path=None,
        git_user_name=None,
        git_user_email=None,
    )
    initialize_database(config)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _setup_data_dir(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[2] / "tests" / "data"
    data_dir = tmp_path / "data"
    shutil.copytree(src, data_dir)
    return data_dir


def test_clone_creates_directory_and_yaml(tmp_path):
    data_dir = _setup_data_dir(tmp_path)
    conn = _make_db(tmp_path)

    record = clone_campaign_directory(
        conn,
        data_dir,
        source_campaign_name="mothersday",
        new_campaign_name="fathersday",
        business_name="acme",
    )
    conn.commit()

    new_dir = data_dir / "acme" / "fathersday"
    new_yaml = new_dir / "fathersday.yaml"
    assert new_dir.is_dir()
    assert new_yaml.exists()
    assert not (new_dir / "mothersday.yaml").exists()

    payload = yaml.safe_load(new_yaml.read_text())
    assert payload["campaign_name"] == "fathersday"
    assert payload["display_name"] == "fathersday"

    conn.close()


def test_clone_generates_title_from_slug(tmp_path):
    data_dir = _setup_data_dir(tmp_path)
    conn = _make_db(tmp_path)

    record = clone_campaign_directory(
        conn,
        data_dir,
        source_campaign_name="mothersday",
        new_campaign_name="main-street-appreciation",
    )
    conn.commit()

    payload = yaml.safe_load((data_dir / "acme" / "main-street-appreciation" / "main-street-appreciation.yaml").read_text())
    assert payload["title"] == "Main Street Appreciation"

    conn.close()


def test_clone_accepts_explicit_title(tmp_path):
    data_dir = _setup_data_dir(tmp_path)
    conn = _make_db(tmp_path)

    record = clone_campaign_directory(
        conn,
        data_dir,
        source_campaign_name="mothersday",
        new_campaign_name="fathersday",
        new_title="Acme Father's Day Event",
    )
    conn.commit()

    payload = yaml.safe_load((data_dir / "acme" / "fathersday" / "fathersday.yaml").read_text())
    assert payload["title"] == "Acme Father's Day Event"

    conn.close()


def test_clone_syncs_to_db(tmp_path):
    import sqlite3 as _sqlite3

    data_dir = _setup_data_dir(tmp_path)
    conn = _make_db(tmp_path)

    clone_campaign_directory(
        conn,
        data_dir,
        source_campaign_name="mothersday",
        new_campaign_name="fathersday",
        business_name="acme",
    )
    conn.commit()

    row = conn.execute(
        "SELECT campaign_name FROM campaigns WHERE campaign_name = 'fathersday';"
    ).fetchone()
    assert row is not None
    assert row["campaign_name"] == "fathersday"

    conn.close()


def test_clone_raises_if_source_not_found(tmp_path):
    data_dir = _setup_data_dir(tmp_path)
    conn = _make_db(tmp_path)

    with pytest.raises(ValueError, match="not found"):
        clone_campaign_directory(
            conn,
            data_dir,
            source_campaign_name="nonexistent-campaign",
            new_campaign_name="whatever",
        )

    conn.close()


def test_clone_raises_if_dest_exists(tmp_path):
    data_dir = _setup_data_dir(tmp_path)
    conn = _make_db(tmp_path)

    # Clone once
    clone_campaign_directory(
        conn, data_dir, source_campaign_name="mothersday", new_campaign_name="fathersday"
    )
    conn.commit()

    # Clone again to same name — should raise
    with pytest.raises(ValueError, match="already exists"):
        clone_campaign_directory(
            conn, data_dir, source_campaign_name="mothersday", new_campaign_name="fathersday"
        )

    conn.close()


# ---------------------------------------------------------------------------
# Chat endpoint integration
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, data_dir: Path) -> Path:
    return write_isolated_config(
        tmp_path,
        runtime_data_dir=tmp_path / "data-runtime",
        test_data_dir=data_dir,
        runtime_database_path=tmp_path / "db" / "runtime.db",
        test_database_path=tmp_path / "db" / "test.db",
    )


def test_chat_clone_via_endpoint(tmp_path, monkeypatch):
    data_dir = _setup_data_dir(tmp_path)
    config_path = _write_config(tmp_path, data_dir)
    client = make_test_client(monkeypatch, config_path)

    # Seed the DB by syncing the data dir
    resp = client.post("/data/sync")
    assert resp.status_code == 200, resp.text

    # Create a chat session (campaign_id is optional for clone commands)
    session_id = client.post("/chat/sessions").json()["session_id"]

    msg = "clone mothersday and rename it to fathersday"
    resp = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"message": msg},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["result"]["target"] == "clone"
    assert body["result"]["new_campaign_name"] == "fathersday"
    assert isinstance(body["result"]["new_campaign_id"], int)
    assert isinstance(body["result"]["new_business_id"], int)

    # New YAML directory should exist
    assert (data_dir / "acme" / "fathersday" / "fathersday.yaml").exists()
