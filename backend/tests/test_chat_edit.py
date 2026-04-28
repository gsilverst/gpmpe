from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import yaml

from app.config import resolve_config
from app.db import connect_database

from .conftest import make_test_client, write_isolated_config


def _write_config(
    tmp_path: Path,
    *,
    commit_on_save: bool = True,
    with_git_settings: bool = False,
) -> Path:
    config_path = write_isolated_config(
        tmp_path,
        test_data_dir=tmp_path / "yaml-data-test",
        commit_on_save=commit_on_save,
        git_repo_path="." if with_git_settings else None,
        git_user_name="Test User" if with_git_settings else None,
        git_user_email="test@example.com" if with_git_settings else None,
    )
    return config_path


def _make_client(monkeypatch, config_path: Path) -> TestClient:
    return make_test_client(monkeypatch, config_path)


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


def _seed_component_for_campaign(campaign_id: int) -> None:
    config = resolve_config()
    with connect_database(config) as connection:
        connection.execute(
            """
            INSERT INTO campaign_components (
              campaign_id, component_key, component_kind, display_title, display_order
            )
            VALUES (?, 'mothers-day-specials', 'featured-offers', 'Mothers Day Specials', 1);
            """,
            (campaign_id,),
        )
        connection.commit()


def _seed_component_items_for_campaign(campaign_id: int) -> None:
        config = resolve_config()
        with connect_database(config) as connection:
                component_id = connection.execute(
                        """
                        INSERT INTO campaign_components (
                            campaign_id, component_key, component_kind, display_title, display_order
                        )
                        VALUES (?, 'main-street-appreciation', 'featured-offers', 'Main Street Appreciation', 1)
                        RETURNING id;
                        """,
                        (campaign_id,),
                ).fetchone()["id"]
                connection.execute(
                        """
                        INSERT INTO campaign_component_items (
                            component_id, item_name, item_kind, duration_label, item_value, description_text, terms_text, display_order
                        )
                        VALUES
                            (?, 'Express Facial', 'service', '30 min', '$35', 'Quick glow-up', NULL, 1),
                            (?, 'Signature Facial', 'service', '60 min', '$75', 'Full treatment', NULL, 2);
                        """,
                        (component_id, component_id),
                )
                connection.commit()


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


def test_chat_edit_persists_updates_to_yaml_on_mutation(monkeypatch, tmp_path: Path) -> None:
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

    business_yaml = tmp_path / "yaml-data-test" / "Acme" / "Acme.yaml"
    campaign_yaml = tmp_path / "yaml-data-test" / "Acme" / "Summer" / "Summer.yaml"

    assert business_yaml.exists()
    assert campaign_yaml.exists()

    business_payload = yaml.safe_load(business_yaml.read_text(encoding="utf-8"))
    campaign_payload = yaml.safe_load(campaign_yaml.read_text(encoding="utf-8"))

    assert business_payload["display_name"] == "Acme"
    assert business_payload["brand_theme"]["primary_color"] == "#334455"
    assert campaign_payload["campaign_name"] == "Summer"
    assert campaign_payload["title"] == "YAML Persisted Title"


def test_chat_message_can_rename_component_by_natural_language(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the name of the mothers-day-specials component to main-street-appreciation-month",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component"
    assert payload["result"]["field"] == "component_key"
    assert payload["result"]["component"]["component_key"] == "main-street-appreciation-month"
    assert payload["result"]["component"]["display_title"] == "Mothers Day Specials"


def test_chat_message_can_rename_component_by_display_title(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "set component mothers-day-specials display_title to Main Street Appreciation Month",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component"
    assert payload["result"]["field"] == "display_title"
    assert payload["result"]["component"]["display_title"] == "Main Street Appreciation Month"


def test_chat_message_component_rename_without_new_name_returns_helpful_error(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the name of the mothers-day-specials component",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "clarify"
    assert "Please provide the new component-key" in payload["result"]["message"]


def test_chat_message_can_rename_component_key_with_component_key_field_phrase(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the component-key field of the mothers-day-specials component to main-street-appreciation-month",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component"
    assert payload["result"]["field"] == "component_key"
    assert payload["result"]["component"]["component_key"] == "main-street-appreciation-month"


def test_chat_message_component_key_field_phrase_without_new_name_returns_helpful_error(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the component-key field of the mothers-day-specials component",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "clarify"
    assert "Please provide the new component-key" in payload["result"]["message"]


def test_chat_message_can_update_component_item_field_by_ordinal(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the item_value field of the first item in the main-street-appreciation component to $45",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component_item"
    assert payload["result"]["field"] == "item_value"
    assert payload["result"]["component"]["component_key"] == "main-street-appreciation"
    assert payload["result"]["item"]["item_name"] == "Express Facial"
    assert payload["result"]["item"]["item_value"] == "$45"


def test_chat_message_component_item_field_update_rejects_missing_ordinal_target(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the item_value field of the fifth item in the main-street-appreciation component to $45",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Component item not found"


def test_save_is_noop_when_commit_on_save_disabled(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, commit_on_save=False)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)

    save = client.post(f"/campaigns/{campaign_id}/save")
    assert save.status_code == 200
    payload = save.json()
    assert payload["saved"] is False
    assert payload["reason"] == "commit_on_save_disabled"


def test_save_is_noop_when_git_config_is_incomplete(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, commit_on_save=True, with_git_settings=False)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)

    save = client.post(f"/campaigns/{campaign_id}/save")
    assert save.status_code == 200
    payload = save.json()
    assert payload["saved"] is False
    assert payload["reason"] == "git_config_incomplete"


def test_save_can_commit_when_enabled_and_git_configured(monkeypatch, tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)

    config_path = _write_config(tmp_path, commit_on_save=True, with_git_settings=True)
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
    assert payload["saved"] is True
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
