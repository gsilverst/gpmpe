"""Tests for the new GUI-oriented mutation endpoints (Components and Items)."""
from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from .conftest import make_test_client, write_isolated_config

def _write_config(tmp_path: Path) -> Path:
    return write_isolated_config(
        tmp_path,
        test_data_dir=tmp_path / "yaml-data-test",
        commit_on_save=False,
    )

def _make_client(monkeypatch, config_path: Path) -> TestClient:
    return make_test_client(monkeypatch, config_path)

def _seed_campaign(client: TestClient) -> tuple[int, int]:
    biz_id = client.post(
        "/businesses",
        json={"legal_name": "Test GUI", "display_name": "GUI Test", "timezone": "UTC"}
    ).json()["id"]
    camp_id = client.post(
        f"/businesses/{biz_id}/campaigns",
        json={"campaign_name": "gui-test", "title": "GUI Mutation Test"}
    ).json()["id"]
    return biz_id, camp_id

def test_component_lifecycle(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, camp_id = _seed_campaign(client)

    # 1. Create
    resp = client.post(
        f"/campaigns/{camp_id}/components",
        json={
            "component_key": "featured",
            "display_title": "Featured Offers",
            "component_kind": "featured-offers",
            "display_order": 1
        }
    )
    assert resp.status_code == 201
    comp_id = resp.json()["id"]

    # 2. Update
    resp = client.patch(
        f"/campaigns/{camp_id}/components/{comp_id}",
        json={"display_title": "New Title", "background_color": "blue"}
    )
    assert resp.status_code == 200
    
    # Verify via List
    resp = client.get(f"/campaigns/{camp_id}/components")
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["display_title"] == "New Title"
    assert items[0]["background_color"] == "blue"

    # 3. Delete
    resp = client.delete(f"/campaigns/{camp_id}/components/{comp_id}")
    assert resp.status_code == 204
    
    resp = client.get(f"/campaigns/{camp_id}/components")
    assert len(resp.json()["items"]) == 0

def test_item_lifecycle(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, camp_id = _seed_campaign(client)

    # Create parent component
    comp_id = client.post(
        f"/campaigns/{camp_id}/components",
        json={"component_key": "services", "display_title": "Our Services", "component_kind": "strip-list"}
    ).json()["id"]

    # 1. Create Item
    resp = client.post(
        f"/campaigns/{camp_id}/components/{comp_id}/items",
        json={
            "item_name": "Massage",
            "item_value": "$50",
            "duration_label": "30 min",
            "display_order": 0
        }
    )
    assert resp.status_code == 201
    item_id = resp.json()["id"]

    # 2. Update Item
    resp = client.patch(
        f"/campaigns/{camp_id}/components/{comp_id}/items/{item_id}",
        json={"item_name": "Deep Tissue", "item_value": "$60"}
    )
    assert resp.status_code == 200

    # Verify via List (nested)
    resp = client.get(f"/campaigns/{camp_id}/components")
    comp = resp.json()["items"][0]
    assert len(comp["items"]) == 1
    assert comp["items"][0]["item_name"] == "Deep Tissue"
    assert comp["items"][0]["item_value"] == "$60"

    # 3. Delete Item
    resp = client.delete(f"/campaigns/{camp_id}/components/{comp_id}/items/{item_id}")
    assert resp.status_code == 204
    
    resp = client.get(f"/campaigns/{camp_id}/components")
    assert len(resp.json()["items"][0]["items"]) == 0
