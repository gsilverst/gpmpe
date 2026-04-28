from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import yaml

from app.main import create_app


def _write_config(tmp_path: Path, *, yaml_auto_commit: bool = False) -> Path:
    config_path = tmp_path / ".config"
    output_dir = tmp_path / "output"
    database_path = tmp_path / "data" / "test.db"
    data_dir = tmp_path / "yaml-data"
    config_path.write_text(
        (
            f"OUTPUT_DIR={output_dir}\n"
            f"DATABASE_PATH={database_path}\n"
            f"DATA_DIR={data_dir}\n"
            f"YAML_AUTO_COMMIT={'true' if yaml_auto_commit else 'false'}\n"
        ),
        encoding="utf-8",
    )
    return config_path


def _make_client(monkeypatch, config_path: Path) -> TestClient:
    monkeypatch.setenv("GPMPG_CONFIG_FILE", str(config_path))
    return TestClient(create_app())


def _seed_campaign(client: TestClient) -> tuple[int, int]:
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
            "objective": "Drive sales",
        },
    ).json()["id"]

    return business_id, campaign_id


def test_chat_message_updates_campaign_and_brand(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    business_id, campaign_id = _seed_campaign(client)

    session_id = client.post("/chat/sessions").json()["session_id"]

    update_title = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set title to Weekend Blowout"},
    )
    assert update_title.status_code == 200
    assert update_title.json()["result"]["campaign"]["title"] == "Weekend Blowout"

    update_brand = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set brand primary_color to #112233"},
    )
    assert update_brand.status_code == 200
    assert update_brand.json()["result"]["brand_theme"]["primary_color"] == "#112233"

    campaigns = client.get(f"/businesses/{business_id}/campaigns").json()["items"]
    assert campaigns[0]["title"] == "Weekend Blowout"

    invalid = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "please change it"},
    )
    assert invalid.status_code == 400


def test_chat_offer_edit_rejects_overlap(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)

    offer_one = client.post(
        f"/campaigns/{campaign_id}/offers",
        json={
            "offer_name": "May",
            "offer_value": "20%",
            "start_date": "2026-05-01",
            "end_date": "2026-05-31",
        },
    )
    assert offer_one.status_code == 201

    offer_two = client.post(
        f"/campaigns/{campaign_id}/offers",
        json={
            "offer_name": "June",
            "offer_value": "15%",
            "start_date": "2026-06-01",
            "end_date": "2026-06-30",
        },
    )
    assert offer_two.status_code == 201
    offer_two_id = offer_two.json()["id"]

    session_id = client.post("/chat/sessions").json()["session_id"]

    overlap = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": f"set offer {offer_two_id} start_date to 2026-05-15"},
    )
    assert overlap.status_code == 409
    assert overlap.json()["detail"]["message"] == "Offer date window overlaps with an existing offer"


def test_chat_history_is_transient_but_campaign_state_persists(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    first_client = _make_client(monkeypatch, config_path)
    business_id, campaign_id = _seed_campaign(first_client)

    session_id = first_client.post("/chat/sessions").json()["session_id"]
    update = first_client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set title to Persisted Title"},
    )
    assert update.status_code == 200

    second_client = _make_client(monkeypatch, config_path)

    old_session_lookup = second_client.get(f"/chat/sessions/{session_id}")
    assert old_session_lookup.status_code == 404

    campaigns = second_client.get(f"/businesses/{business_id}/campaigns").json()["items"]
    assert campaigns[0]["title"] == "Persisted Title"


def test_chat_edit_requires_explicit_save_to_persist_yaml(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)

    session_id = client.post("/chat/sessions").json()["session_id"]

    update_title = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set title to YAML Persisted Title"},
    )
    assert update_title.status_code == 200

    update_brand = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set brand primary_color to #334455"},
    )
    assert update_brand.status_code == 200

    business_yaml = tmp_path / "yaml-data" / "Acme" / "Acme.yaml"
    campaign_yaml = tmp_path / "yaml-data" / "Acme" / "Summer" / "Summer.yaml"

    assert not business_yaml.exists()
    assert not campaign_yaml.exists()

    saved = client.post(f"/campaigns/{campaign_id}/save")
    assert saved.status_code == 200
    assert saved.json()["auto_commit"]["enabled"] is False

    assert business_yaml.exists()
    assert campaign_yaml.exists()

    business_payload = yaml.safe_load(business_yaml.read_text(encoding="utf-8"))
    campaign_payload = yaml.safe_load(campaign_yaml.read_text(encoding="utf-8"))

    assert business_payload["display_name"] == "Acme"
    assert business_payload["brand_theme"]["primary_color"] == "#334455"
    assert campaign_payload["campaign_name"] == "Summer"
    assert campaign_payload["title"] == "YAML Persisted Title"


def test_explicit_save_can_auto_commit_when_enabled(monkeypatch, tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True, text=True
    )

    config_path = _write_config(tmp_path, yaml_auto_commit=True)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)

    session_id = client.post("/chat/sessions").json()["session_id"]
    update_title = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set title to Commit Title"},
    )
    assert update_title.status_code == 200

    save = client.post(f"/campaigns/{campaign_id}/save", json={"commit_message": "Save from test"})
    assert save.status_code == 200
    payload = save.json()
    assert payload["auto_commit"]["enabled"] is True
    assert payload["auto_commit"]["performed"] is True
    assert payload["auto_commit"]["commit_id"]

    last_message = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert last_message == "Save from test"
