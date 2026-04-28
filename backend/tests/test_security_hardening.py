"""Security, validation, and operational hardening tests (Step 7)."""
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
    monkeypatch.setenv("GPMPE_CONFIG_FILE", str(config_path))
    return TestClient(create_app())


def _seed_business_and_campaign(client: TestClient) -> tuple[int, int]:
    business_id = client.post(
        "/businesses",
        json={"legal_name": "Acme LLC", "display_name": "Acme", "timezone": "America/New_York"},
    ).json()["id"]
    campaign_id = client.post(
        f"/businesses/{business_id}/campaigns",
        json={"campaign_name": "Spring", "title": "Spring Sale"},
    ).json()["id"]
    return business_id, campaign_id


# ---------------------------------------------------------------------------
# Field length bounds
# ---------------------------------------------------------------------------


def test_oversized_legal_name_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.post(
        "/businesses",
        json={
            "legal_name": "A" * 201,
            "display_name": "Acme",
            "timezone": "America/New_York",
        },
    )
    assert response.status_code == 422


def test_oversized_display_name_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.post(
        "/businesses",
        json={
            "legal_name": "Acme LLC",
            "display_name": "B" * 101,
            "timezone": "America/New_York",
        },
    )
    assert response.status_code == 422


def test_oversized_timezone_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.post(
        "/businesses",
        json={
            "legal_name": "Acme LLC",
            "display_name": "Acme",
            "timezone": "T" * 61,
        },
    )
    assert response.status_code == 422


def test_oversized_campaign_name_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    business_id, _ = _seed_business_and_campaign(client)
    response = client.post(
        f"/businesses/{business_id}/campaigns",
        json={"campaign_name": "C" * 201, "title": "Title"},
    )
    assert response.status_code == 422


def test_oversized_campaign_title_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    business_id, _ = _seed_business_and_campaign(client)
    response = client.post(
        f"/businesses/{business_id}/campaigns",
        json={"campaign_name": "Fall", "title": "T" * 301},
    )
    assert response.status_code == 422


def test_oversized_offer_name_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    _, campaign_id = _seed_business_and_campaign(client)
    response = client.post(
        f"/campaigns/{campaign_id}/offers",
        json={"offer_name": "O" * 201, "offer_value": "10%"},
    )
    assert response.status_code == 422


def test_oversized_terms_text_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    _, campaign_id = _seed_business_and_campaign(client)
    response = client.post(
        f"/campaigns/{campaign_id}/offers",
        json={"offer_name": "June", "offer_value": "10%", "terms_text": "X" * 2001},
    )
    assert response.status_code == 422


def test_oversized_chat_message_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    _, campaign_id = _seed_business_and_campaign(client)
    session = client.post("/chat/sessions").json()
    response = client.post(
        f"/chat/sessions/{session['session_id']}/messages",
        json={"campaign_id": campaign_id, "message": "M" * 4001},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Path traversal prevention
# ---------------------------------------------------------------------------


def test_path_traversal_in_source_path_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    _, campaign_id = _seed_business_and_campaign(client)
    response = client.post(
        f"/campaigns/{campaign_id}/assets",
        json={
            "asset_type": "hero_image",
            "source_type": "upload",
            "mime_type": "image/png",
            "source_path": "../../etc/passwd",
        },
    )
    assert response.status_code == 422


def test_nested_path_traversal_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    _, campaign_id = _seed_business_and_campaign(client)
    response = client.post(
        f"/campaigns/{campaign_id}/assets",
        json={
            "asset_type": "logo",
            "source_type": "upload",
            "mime_type": "image/png",
            "source_path": "assets/../../../secret.png",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# URL source_type validation
# ---------------------------------------------------------------------------


def test_non_https_url_source_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    _, campaign_id = _seed_business_and_campaign(client)
    response = client.post(
        f"/campaigns/{campaign_id}/assets",
        json={
            "asset_type": "hero_image",
            "source_type": "url",
            "mime_type": "image/png",
            "source_path": "ftp://example.com/image.png",
        },
    )
    assert response.status_code == 422


def test_plain_path_for_url_source_type_is_rejected(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    _, campaign_id = _seed_business_and_campaign(client)
    response = client.post(
        f"/campaigns/{campaign_id}/assets",
        json={
            "asset_type": "hero_image",
            "source_type": "url",
            "mime_type": "image/png",
            "source_path": "assets/hero.png",
        },
    )
    assert response.status_code == 422


def test_valid_https_url_source_is_accepted(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    _, campaign_id = _seed_business_and_campaign(client)
    response = client.post(
        f"/campaigns/{campaign_id}/assets",
        json={
            "asset_type": "hero_image",
            "source_type": "url",
            "mime_type": "image/png",
            "source_path": "https://cdn.example.com/images/hero.png",
        },
    )
    assert response.status_code == 201


# ---------------------------------------------------------------------------
# Request ID middleware
# ---------------------------------------------------------------------------


def test_request_id_is_returned_in_response_header(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert "x-request-id" in response.headers


def test_custom_request_id_is_echoed_back(monkeypatch, tmp_path: Path) -> None:
    client = _make_client(monkeypatch, tmp_path)
    custom_id = "test-request-id-abc123"
    response = client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == custom_id
