from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def _make_client(monkeypatch, tmp_path: Path) -> TestClient:
    config_path = tmp_path / ".config"
    output_dir = tmp_path / "output"
    database_path = tmp_path / "data" / "test.db"
    data_dir = tmp_path / "yaml-data"
    config_path.write_text(
        f"OUTPUT_DIR={output_dir}\nDATABASE_PATH={database_path}\nDATA_DIR={data_dir}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GPMPG_CONFIG_FILE", str(config_path))
    return TestClient(create_app())


def _seed_campaign(client: TestClient) -> int:
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
            "campaign_name": "Summer",
            "title": "Summer Sale",
        },
    ).json()["id"]
    return campaign_id


def test_offer_windows_reject_overlap(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    campaign_id = _seed_campaign(client)

    first = client.post(
        f"/campaigns/{campaign_id}/offers",
        json={
            "offer_name": "May Offer",
            "offer_value": "20%",
            "start_date": "2026-05-01",
            "end_date": "2026-05-31",
        },
    )
    assert first.status_code == 201

    overlap = client.post(
        f"/campaigns/{campaign_id}/offers",
        json={
            "offer_name": "Overlap",
            "offer_value": "15%",
            "start_date": "2026-05-15",
            "end_date": "2026-06-01",
        },
    )
    assert overlap.status_code == 409
    assert overlap.json()["detail"]["message"] == "Offer date window overlaps with an existing offer"

    next_offer = client.post(
        f"/campaigns/{campaign_id}/offers",
        json={
            "offer_name": "June Offer",
            "offer_value": "10%",
            "start_date": "2026-06-02",
            "end_date": "2026-06-30",
        },
    )
    assert next_offer.status_code == 201


def test_asset_metadata_validation(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    campaign_id = _seed_campaign(client)

    invalid = client.post(
        f"/campaigns/{campaign_id}/assets",
        json={
            "asset_type": "hero_image",
            "source_type": "upload",
            "mime_type": "application/zip",
            "source_path": "assets/hero.zip",
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "Unsupported mime_type"

    valid = client.post(
        f"/campaigns/{campaign_id}/assets",
        json={
            "asset_type": "hero_image",
            "source_type": "upload",
            "mime_type": "image/png",
            "source_path": "assets/hero.png",
            "width": 1200,
            "height": 800,
            "metadata": {"alt": "Hero image", "focus": "center"},
        },
    )
    assert valid.status_code == 201
    payload = valid.json()
    assert payload["mime_type"] == "image/png"
    assert payload["width"] == 1200
    assert payload["metadata"]["alt"] == "Hero image"


def test_template_override_precedence(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    campaign_id = _seed_campaign(client)

    template = client.post(
        "/templates",
        json={
            "template_name": "flyer-standard",
            "template_kind": "flyer",
            "size_spec": "A4",
            "default_values": {
                "headline": "Default Headline",
                "cta": "Visit Today",
                "accent": "#209dd7",
            },
        },
    )
    assert template.status_code == 201
    template_id = template.json()["id"]

    binding = client.post(
        f"/campaigns/{campaign_id}/template-bindings",
        json={
            "template_id": template_id,
            "override_values": {
                "headline": "Campaign Headline",
                "cta": "Shop Now",
            },
        },
    )
    assert binding.status_code == 201

    effective = client.get(f"/campaigns/{campaign_id}/template-binding/effective")
    assert effective.status_code == 200
    payload = effective.json()
    assert payload["default_values"]["headline"] == "Default Headline"
    assert payload["override_values"]["headline"] == "Campaign Headline"
    assert payload["effective_values"]["headline"] == "Campaign Headline"
    assert payload["effective_values"]["cta"] == "Shop Now"
    assert payload["effective_values"]["accent"] == "#209dd7"
