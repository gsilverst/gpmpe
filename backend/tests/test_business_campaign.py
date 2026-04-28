from pathlib import Path
import yaml

from fastapi.testclient import TestClient

from .conftest import make_test_client, write_isolated_config


def _make_client(monkeypatch, tmp_path: Path) -> TestClient:
    config_path = write_isolated_config(tmp_path, test_data_dir=tmp_path / "yaml-data-test")
    return make_test_client(monkeypatch, config_path)


def test_create_new_campaign_for_new_business(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    business_response = client.post(
        "/businesses",
        json={
            "legal_name": "Acme LLC",
            "display_name": "Acme",
            "timezone": "America/New_York",
        },
    )
    assert business_response.status_code == 201
    business_id = business_response.json()["id"]

    campaign_response = client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Mothers Day",
            "title": "Mother's Day Special",
            "objective": "Increase weekend sales",
        },
    )

    assert campaign_response.status_code == 201
    payload = campaign_response.json()
    assert payload["business_id"] == business_id
    assert payload["campaign_name"] == "Mothers Day"
    assert payload["campaign_key"] is None


def test_get_business_and_campaign_detail_endpoints(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    business_id = client.post(
        "/businesses",
        json={
            "legal_name": "Acme LLC",
            "display_name": "Acme",
            "timezone": "America/New_York",
        },
    ).json()["id"]

    campaign_id = client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Spring",
            "title": "Spring Promo",
        },
    ).json()["id"]

    business_detail = client.get(f"/businesses/{business_id}")
    assert business_detail.status_code == 200
    assert business_detail.json()["display_name"] == "Acme"

    campaign_detail = client.get(f"/businesses/{business_id}/campaigns/{campaign_id}")
    assert campaign_detail.status_code == 200
    assert campaign_detail.json()["campaign_name"] == "Spring"


def test_create_new_campaign_for_existing_business(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    business_response = client.post(
        "/businesses",
        json={
            "legal_name": "Beacon Wellness Inc",
            "display_name": "Beacon",
            "timezone": "America/New_York",
        },
    )
    business_id = business_response.json()["id"]

    first = client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Holiday",
            "title": "Holiday 2025",
        },
    )
    assert first.status_code == 201

    second = client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Spring",
            "title": "Spring Sale",
            "status": "active",
        },
    )
    assert second.status_code == 201

    listed = client.get(f"/businesses/{business_id}/campaigns")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 2


def test_modify_existing_campaign(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    business_id = client.post(
        "/businesses",
        json={
            "legal_name": "Bravo Ltd",
            "display_name": "Bravo",
            "timezone": "America/New_York",
        },
    ).json()["id"]

    campaign_id = client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Mothers Day",
            "title": "Original",
        },
    ).json()["id"]

    updated = client.patch(
        f"/businesses/{business_id}/campaigns/{campaign_id}",
        json={
            "title": "Mother's Day 2025",
            "status": "active",
            "objective": "Drive traffic",
        },
    )

    assert updated.status_code == 200
    payload = updated.json()
    assert payload["title"] == "Mother's Day 2025"
    assert payload["status"] == "active"
    assert payload["objective"] == "Drive traffic"


def test_duplicate_campaign_name_requires_secondary_key(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    business_id = client.post(
        "/businesses",
        json={
            "legal_name": "Delta LLC",
            "display_name": "Delta",
            "timezone": "America/New_York",
        },
    ).json()["id"]

    first = client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Mothers Day",
            "title": "Mother's Day 2025",
        },
    )
    assert first.status_code == 201

    duplicate_name = client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Mothers Day",
            "title": "Mother's Day New",
        },
    )
    assert duplicate_name.status_code == 409
    detail = duplicate_name.json()["detail"]
    assert detail["resolution"] == "open_existing_or_create_new"
    assert len(detail["matches"]) == 1

    keyed = client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Mothers Day",
            "campaign_key": "2026",
            "title": "Mother's Day 2026",
        },
    )
    assert keyed.status_code == 201
    assert keyed.json()["campaign_key"] == "2026"

    lookup = client.get(
        f"/businesses/{business_id}/campaigns/lookup",
        params={"campaign_name": "Mothers Day"},
    )
    assert lookup.status_code == 200
    payload = lookup.json()
    assert payload["prompt"] == "open_existing_or_create_new"
    assert len(payload["matches"]) == 2


def test_campaign_status_validation_rejects_invalid_value(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    business_id = client.post(
        "/businesses",
        json={
            "legal_name": "Echo LLC",
            "display_name": "Echo",
            "timezone": "America/New_York",
        },
    ).json()["id"]

    response = client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Summer",
            "title": "Summer",
            "status": "invalid-status",
        },
    )

    assert response.status_code == 422


def test_campaign_create_and_update_persist_to_yaml(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    business_id = client.post(
        "/businesses",
        json={
            "legal_name": "Acme LLC",
            "display_name": "Acme",
            "timezone": "America/New_York",
        },
    ).json()["id"]

    created = client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Summer",
            "title": "Summer Launch",
            "objective": "Increase awareness",
            "status": "draft",
        },
    )
    assert created.status_code == 201
    campaign_id = created.json()["id"]

    updated = client.patch(
        f"/businesses/{business_id}/campaigns/{campaign_id}",
        json={
            "title": "Summer Launch Updated",
            "objective": "Increase store visits",
            "status": "active",
        },
    )
    assert updated.status_code == 200

    campaign_yaml = tmp_path / "yaml-data-test" / "Acme" / "Summer" / "Summer.yaml"
    assert campaign_yaml.exists()

    payload = yaml.safe_load(campaign_yaml.read_text(encoding="utf-8"))
    assert payload["campaign_name"] == "Summer"
    assert payload["title"] == "Summer Launch Updated"
    assert payload["objective"] == "Increase store visits"
    assert payload["status"] == "active"


def test_business_update_persists_to_yaml_when_campaign_exists(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    business_id = client.post(
        "/businesses",
        json={
            "legal_name": "Acme LLC",
            "display_name": "Acme",
            "timezone": "America/New_York",
        },
    ).json()["id"]

    client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Summer",
            "title": "Summer Launch",
        },
    )

    updated = client.patch(
        f"/businesses/{business_id}",
        json={
            "legal_name": "Acme Holdings LLC",
            "timezone": "America/Chicago",
            "is_active": False,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["legal_name"] == "Acme Holdings LLC"
    assert updated.json()["timezone"] == "America/Chicago"
    assert updated.json()["is_active"] is False

    business_yaml = tmp_path / "yaml-data-test" / "Acme" / "Acme.yaml"
    assert business_yaml.exists()
    payload = yaml.safe_load(business_yaml.read_text(encoding="utf-8"))
    assert payload["legal_name"] == "Acme Holdings LLC"
    assert payload["timezone"] == "America/Chicago"
    assert payload["is_active"] is False
