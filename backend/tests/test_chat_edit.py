from pathlib import Path
import sqlite3
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


def _seed_template_binding(client: TestClient, campaign_id: int, overrides: dict | None = None) -> int:
    template_id = client.post(
        "/templates",
        json={
            "template_name": f"flyer-{campaign_id}",
            "template_kind": "flyer",
            "size_spec": "letter",
            "layout": {"version": 1},
            "default_values": {"footer_font_size": 10},
        },
    ).json()["id"]

    response = client.post(
        f"/campaigns/{campaign_id}/template-bindings",
        json={"template_id": template_id, "override_values": overrides or {}},
    )
    assert response.status_code == 201
    return response.json()["id"]


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
            VALUES (?, 'community-appreciation', 'featured-offers', 'Town Center Appreciation', 1)
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


def _seed_massage_component_items_for_campaign(campaign_id: int) -> None:
    config = resolve_config()
    with connect_database(config) as connection:
        component_id = connection.execute(
            """
            INSERT INTO campaign_components (
                campaign_id, component_key, component_kind, display_title, display_order
            )
            VALUES (?, 'community-appreciation', 'featured-offers', 'Town Center Appreciation', 1)
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
                (?, 'Swedish Massage', 'service', '60 min', '$75', 'Relaxing full-body massage', NULL, 1),
                (?, 'Deep Tissue', 'service', '60 min', '$95', 'Targeted muscle relief', NULL, 2),
                (?, 'Hot Stone', 'service', '75 min', '$110', 'Heated stone therapy', NULL, 3);
            """,
            (component_id, component_id, component_id),
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


def test_chat_message_can_update_template_footer_font_size(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    binding_id = _seed_template_binding(client, campaign_id, {"footer": "example.com | 555-0100"})

    session_id = client.post("/chat/sessions").json()["session_id"]

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set footer font size to 14"},
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["target"] == "template_override"
    assert result["field"] == "footer_font_size"
    assert result["template_binding_id"] == binding_id
    assert result["override_values"]["footer_font_size"] == 14

    config = resolve_config()
    with connect_database(config) as connection:
        row = connection.execute(
            "SELECT override_values_json FROM campaign_template_bindings WHERE id = ?;",
            (binding_id,),
        ).fetchone()
    assert row is not None
    assert yaml.safe_load(row["override_values_json"])["footer_font_size"] == 14

    campaign_yaml = tmp_path / "yaml-data-test" / "Acme" / "Summer" / "Summer.yaml"
    campaign_payload = yaml.safe_load(campaign_yaml.read_text(encoding="utf-8"))
    assert campaign_payload["template_binding"]["override_values"]["footer_font_size"] == 14


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
            "message": "change the name of the mothers-day-specials component to community-appreciation-month",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component"
    assert payload["result"]["field"] == "component_key"
    assert payload["result"]["component"]["component_key"] == "community-appreciation-month"
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
            "message": "set component mothers-day-specials display_title to Town Center Appreciation Month",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component"
    assert payload["result"]["field"] == "display_title"
    assert payload["result"]["component"]["display_title"] == "Town Center Appreciation Month"


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
            "message": "change the component-key field of the mothers-day-specials component to community-appreciation-month",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component"
    assert payload["result"]["field"] == "component_key"
    assert payload["result"]["component"]["component_key"] == "community-appreciation-month"


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
            "message": "change the item_value field of the first item in the community-appreciation component to $45",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component_item"
    assert payload["result"]["field"] == "item_value"
    assert payload["result"]["component"]["component_key"] == "community-appreciation"
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
            "message": "change the item_value field of the fifth item in the community-appreciation component to $45",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Component item not found"


def test_chat_message_can_update_component_item_field_by_item_name(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the item_value field of the Signature Facial item in the community-appreciation component to $45",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component_item"
    assert payload["result"]["field"] == "item_value"
    assert payload["result"]["item"]["item_name"] == "Signature Facial"
    assert payload["result"]["item"]["item_value"] == "$45"


def test_chat_message_can_update_component_item_field_with_item_first_phrase(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the Signature Facial item value in the community-appreciation component to $45",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component_item"
    assert payload["result"]["field"] == "item_value"
    assert payload["result"]["item"]["item_name"] == "Signature Facial"
    assert payload["result"]["item"]["item_value"] == "$45"


def test_chat_message_can_update_component_background_color(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the background color of the mothers-day-specials component to light green",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component"
    assert payload["result"]["field"] == "background_color"
    assert payload["result"]["component"]["component_key"] == "mothers-day-specials"
    assert payload["result"]["component"]["background_color"] == "light green"


def test_chat_message_can_update_component_header_accent_color(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "set the header_accent_color of the mothers-day-specials component to black",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component"
    assert payload["result"]["field"] == "header_accent_color"
    assert payload["result"]["component"]["component_key"] == "mothers-day-specials"
    assert payload["result"]["component"]["header_accent_color"] == "black"


def test_chat_message_can_update_component_text_color_alias(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "set the text color of the mothers-day-specials component to black",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["field"] == "header_accent_color"
    assert payload["result"]["component"]["header_accent_color"] == "black"


def test_chat_message_can_update_component_item_background_color(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the Signature Facial item background color in the community-appreciation component to #cfeccf",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component_item"
    assert payload["result"]["field"] == "background_color"
    assert payload["result"]["item"]["item_name"] == "Signature Facial"
    assert payload["result"]["item"]["background_color"] == "#cfeccf"


def test_chat_message_can_update_background_for_all_items_in_active_component(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]

    context_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "I am working on the community-appreciation component",
        },
    )
    assert context_response.status_code == 200

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the color of the background to light purple for all items.",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component_item"
    assert payload["result"]["field"] == "background_color"
    assert payload["result"]["scope"] == "all_items"
    assert payload["result"]["updated_count"] == 2

    config = resolve_config()
    with connect_database(config) as connection:
        rows = connection.execute(
            """
            SELECT item_name, background_color
            FROM campaign_component_items
            WHERE component_id = (
              SELECT id FROM campaign_components
              WHERE campaign_id = ? AND component_key = 'community-appreciation'
            )
            ORDER BY display_order ASC, id ASC;
            """,
            (campaign_id,),
        ).fetchall()

    assert [r["background_color"] for r in rows] == ["light purple", "light purple"]


def test_chat_message_can_update_background_of_items_of_component(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "set the background color of the items of the community-appreciation component to white",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component_item"
    assert payload["result"]["field"] == "background_color"
    assert payload["result"]["scope"] == "all_items"
    assert payload["result"]["updated_count"] == 2

    config = resolve_config()
    with connect_database(config) as connection:
        rows = connection.execute(
            """
            SELECT item_name, background_color
            FROM campaign_component_items
            WHERE component_id = (
              SELECT id FROM campaign_components
              WHERE campaign_id = ? AND component_key = 'community-appreciation'
            )
            ORDER BY display_order ASC, id ASC;
            """,
            (campaign_id,),
        ).fetchall()

    assert [r["background_color"] for r in rows] == ["white", "white"]


def test_chat_message_can_update_background_for_all_components(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the background color to lavender for all components.",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component"
    assert payload["result"]["field"] == "background_color"
    assert payload["result"]["scope"] == "all_components"
    assert payload["result"]["updated_count"] == 2

    config = resolve_config()
    with connect_database(config) as connection:
        rows = connection.execute(
            """
            SELECT component_key, background_color
            FROM campaign_components
            WHERE campaign_id = ?
            ORDER BY display_order ASC, id ASC;
            """,
            (campaign_id,),
        ).fetchall()

    assert all(r["background_color"] == "lavender" for r in rows)


def test_chat_message_can_clone_component_item_with_new_name_between_neighbors(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_massage_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]

    context_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "I am working on the community-appreciation component",
        },
    )
    assert context_response.status_code == 200

    clone_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "create a new item like the Swedish Massage item called Lymphatic Drainage and add it between the Swedish Massage and the Deep Tissue items",
        },
    )

    assert clone_response.status_code == 200
    payload = clone_response.json()
    assert payload["result"]["target"] == "component_item"
    assert payload["result"]["field"] == "clone"
    assert payload["result"]["component"]["component_key"] == "community-appreciation"
    assert payload["result"]["item"]["item_name"] == "Lymphatic Drainage"
    assert payload["result"]["item"]["item_value"] == "$75"
    assert payload["result"]["item"]["display_order"] == 2

    config = resolve_config()
    with connect_database(config) as connection:
        items = connection.execute(
            """
            SELECT item_name, display_order
            FROM campaign_component_items
            WHERE component_id = (
                SELECT id
                FROM campaign_components
                WHERE campaign_id = ? AND component_key = 'community-appreciation'
            )
            ORDER BY display_order ASC, id ASC;
            """,
            (campaign_id,),
        ).fetchall()

    assert [(item["item_name"], item["display_order"]) for item in items] == [
        ("Swedish Massage", 1),
        ("Lymphatic Drainage", 2),
        ("Deep Tissue", 3),
        ("Hot Stone", 4),
    ]


def test_chat_message_can_delete_component_item_by_ordinal_with_context(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]

    context_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "I am working on the community-appreciation component",
        },
    )
    assert context_response.status_code == 200

    delete_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "delete the second item",
        },
    )

    assert delete_response.status_code == 200
    payload = delete_response.json()
    assert payload["result"]["target"] == "component_item"
    assert payload["result"]["field"] == "delete"
    assert payload["result"]["deleted"] is True
    assert payload["result"]["item"]["item_name"] == "Signature Facial"

    config = resolve_config()
    with connect_database(config) as connection:
        items = connection.execute(
            """
            SELECT item_name, display_order
            FROM campaign_component_items
            WHERE component_id = (
                SELECT id
                FROM campaign_components
                WHERE campaign_id = ? AND component_key = 'community-appreciation'
            )
            ORDER BY display_order ASC, id ASC;
            """,
            (campaign_id,),
        ).fetchall()

    assert [(item["item_name"], item["display_order"]) for item in items] == [
        ("Express Facial", 1),
    ]


def test_chat_message_can_delete_component_item_by_name(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "delete the Signature Facial item in the community-appreciation component",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component_item"
    assert payload["result"]["field"] == "delete"
    assert payload["result"]["deleted"] is True
    assert payload["result"]["item"]["item_name"] == "Signature Facial"


def test_chat_message_can_delete_component_by_name(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "delete the community-appreciation component",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component"
    assert payload["result"]["field"] == "delete"
    assert payload["result"]["deleted"] is True
    assert payload["result"]["component"]["component_key"] == "community-appreciation"

    config = resolve_config()
    with connect_database(config) as connection:
        component = connection.execute(
            """
            SELECT id
            FROM campaign_components
            WHERE campaign_id = ? AND component_key = 'community-appreciation';
            """,
            (campaign_id,),
        ).fetchone()

    assert component is None


def test_chat_message_component_item_field_update_rejects_missing_named_target(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the item_value field of the Deluxe Facial item in the community-appreciation component to $45",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Component item not found"


def test_chat_message_can_set_active_component_context_and_edit_item_without_component_name(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]

    context_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "I am working on the community-appreciation component",
        },
    )
    assert context_response.status_code == 200
    context_payload = context_response.json()
    assert context_payload["result"]["target"] == "context"
    assert context_payload["result"]["component"]["component_key"] == "community-appreciation"

    edit_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the item_value field of the Signature Facial item to $45",
        },
    )

    assert edit_response.status_code == 200
    edit_payload = edit_response.json()
    assert edit_payload["result"]["target"] == "component_item"
    assert edit_payload["result"]["component"]["component_key"] == "community-appreciation"
    assert edit_payload["result"]["item"]["item_name"] == "Signature Facial"
    assert edit_payload["result"]["item"]["item_value"] == "$45"


def test_chat_message_item_edit_without_component_context_returns_clarify(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the item_value field of the Signature Facial item to $45",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "clarify"
    assert "which component you are working on" in payload["result"]["message"]


def test_component_rename_updates_active_component_context_automatically(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]

    rename_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the name of the community-appreciation component to other-services",
        },
    )
    assert rename_response.status_code == 200
    rename_payload = rename_response.json()
    assert rename_payload["result"]["component"]["component_key"] == "other-services"

    edit_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the item_value field of the Signature Facial item to $45",
        },
    )
    assert edit_response.status_code == 200
    edit_payload = edit_response.json()
    assert edit_payload["result"]["target"] == "component_item"
    assert edit_payload["result"]["component"]["component_key"] == "other-services"
    assert edit_payload["result"]["item"]["item_value"] == "$45"


def test_changing_campaign_clears_stale_component_context(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    business_id, first_campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(first_campaign_id)

    second_campaign_id = client.post(
        f"/businesses/{business_id}/campaigns",
        json={
            "campaign_name": "Winter",
            "title": "Winter Sale",
            "objective": "Drive winter sales",
        },
    ).json()["id"]

    session_id = client.post("/chat/sessions").json()["session_id"]

    context_response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": first_campaign_id,
            "message": "change the item_value field of the Signature Facial item in the community-appreciation component to $45",
        },
    )
    assert context_response.status_code == 200

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": second_campaign_id,
            "message": "change the item_value field of the Signature Facial item to $65",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "clarify"
    assert "which component you are working on" in payload["result"]["message"]


def test_chat_message_short_field_aliases(monkeypatch, tmp_path: Path) -> None:
    """Short/natural field names should be accepted and normalized to canonical field names."""
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]

    # Campaign alias: "headline" → "title"
    r = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set headline to Flash Sale"},
    )
    assert r.status_code == 200
    assert r.json()["result"]["campaign"]["title"] == "Flash Sale"

    # Brand alias: "primary" → "primary_color"
    r = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set brand primary to #aabbcc"},
    )
    assert r.status_code == 200
    assert r.json()["result"]["brand_theme"]["primary_color"] == "#aabbcc"

    # Brand alias: "primary color" → "primary_color"
    r = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set brand primary color to #bbccdd"},
    )
    assert r.status_code == 200
    assert r.json()["result"]["brand_theme"]["primary_color"] == "#bbccdd"

    # Item alias: "value" → "item_value" with "set ... of ... item to" phrasing
    r = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "set the value of the Express Facial item in the community-appreciation component to $40",
        },
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["target"] == "component_item"
    assert result["item"]["item_name"] == "Express Facial"
    assert result["item"]["item_value"] == "$40"

    # Item alias: "price" → "item_value"
    r = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the price of the Signature Facial item in the community-appreciation component to $80",
        },
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["item"]["item_name"] == "Signature Facial"
    assert result["item"]["item_value"] == "$80"

    # Item alias: "duration" → "duration_label"
    r = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the duration of the Express Facial item in the community-appreciation component to 45 min",
        },
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["item"]["item_name"] == "Express Facial"
    assert result["item"]["duration_label"] == "45 min"


def test_chat_message_can_update_campaign_footnote_with_short_alias(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set footnote to Restrictions apply. See store for details."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "campaign"
    assert payload["result"]["field"] == "footnote_text"
    assert payload["result"]["campaign"]["footnote_text"] == "Restrictions apply. See store for details."


def test_chat_message_can_update_component_metadata_fields_with_aliases(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the kind of the mothers-day-specials component to legal-note",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["field"] == "component_kind"
    assert response.json()["result"]["component"]["component_kind"] == "legal-note"

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the description of the mothers-day-specials component to Limited-time neighborhood appreciation offers",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["field"] == "description_text"
    assert response.json()["result"]["component"]["description_text"] == "Limited-time neighborhood appreciation offers"

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "change the footnote of the mothers-day-specials component to Offers valid Monday through Thursday only",
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["field"] == "footnote_text"
    assert response.json()["result"]["component"]["footnote_text"] == "Offers valid Monday through Thursday only"


def test_chat_message_can_update_business_profile_fields(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    business_id, campaign_id = _seed_campaign(client)

    seed_address = client.patch(
        f"/businesses/{business_id}",
        json={
            "phone": "(201) 555-0100",
            "address_line1": "263 Market St.",
            "city": "Springfield",
            "state": "NJ",
            "postal_code": "07601",
            "country": "US",
        },
    )
    assert seed_address.status_code == 200

    session_id = client.post("/chat/sessions").json()["session_id"]

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set business display name to Acme Wellness"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["target"] == "business"
    assert response.json()["result"]["business"]["display_name"] == "Acme Wellness"

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set business active to false"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["business"]["is_active"] is False

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set business city to Teaneck"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["business"]["city"] == "Teaneck"

    business = client.get(f"/businesses/{business_id}")
    assert business.status_code == 200
    business_payload = business.json()
    assert business_payload["display_name"] == "Acme Wellness"
    assert business_payload["is_active"] is False
    assert business_payload["city"] == "Teaneck"


def test_chat_message_can_list_components_of_current_promotion(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "what are the components of the current promotion"},
    )
    assert response.status_code == 200
    payload = response.json()
    result = payload["result"]
    assert result["target"] == "query"
    assert result["query_type"] == "list_components"
    keys = [c["component_key"] for c in result["components"]]
    assert "mothers-day-specials" in keys
    assert "community-appreciation" in keys
    assert "mothers-day-specials" in result["message"]
    assert "community-appreciation" in result["message"]


def test_chat_message_can_list_items_of_active_component(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]

    # Establish active component context
    client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "I am working on the community-appreciation component"},
    )

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "what are the items of the current component"},
    )
    assert response.status_code == 200
    payload = response.json()
    result = payload["result"]
    assert result["target"] == "query"
    assert result["query_type"] == "list_items"
    assert result["component_key"] == "community-appreciation"
    item_names = [it["item_name"] for it in result["items"]]
    assert "Express Facial" in item_names
    assert "Signature Facial" in item_names
    assert "Express Facial" in result["message"]
    assert "Signature Facial" in result["message"]


def test_chat_message_list_items_without_active_component_returns_clarify(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "list the items"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "clarify"
    assert "No active component" in payload["result"]["message"]


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


def test_chat_message_can_add_new_item_with_positioning(monkeypatch, tmp_path: Path):
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    
    config = resolve_config()
    with connect_database(config) as connection:
        # Setup: one campaign with two items
        connection.execute("INSERT INTO businesses (display_name, legal_name) VALUES ('Acme', 'Acme Corp');")
        connection.execute("INSERT INTO campaigns (business_id, campaign_name, title) VALUES (1, 'spring', 'Spring Sale');")
        connection.execute(
            "INSERT INTO campaign_components (campaign_id, component_key, display_title, display_order) "
            "VALUES (1, 'featured', 'Featured', 1);"
        )
        connection.execute(
            "INSERT INTO campaign_component_items (component_id, item_name, item_kind, item_value, display_order) "
            "VALUES (1, 'Item 1', 'service', '$10', 1);"
        )
        connection.execute(
            "INSERT INTO campaign_component_items (component_id, item_name, item_kind, item_value, display_order) "
            "VALUES (1, 'Item 2', 'service', '$20', 2);"
        )
        connection.commit()

    session_id = client.post("/chat/sessions").json()["session_id"]

    # 1. Add to end
    resp = client.post(f"/chat/sessions/{session_id}/messages", json={
        "message": "add a new item called Item 3 to the featured component",
        "campaign_id": 1
    })
    assert resp.status_code == 200
    
    with connect_database(config) as connection:
        items = connection.execute("SELECT item_name FROM campaign_component_items WHERE component_id = 1 ORDER BY display_order").fetchall()
    assert [row["item_name"] for row in items] == ["Item 1", "Item 2", "Item 3"]

    # 2. Add before relative
    resp = client.post(f"/chat/sessions/{session_id}/messages", json={
        "message": "add a new item called Item 1.5 before the Item 2 item in the featured component",
        "campaign_id": 1
    })
    assert resp.status_code == 200
    
    with connect_database(config) as connection:
        items = connection.execute("SELECT item_name FROM campaign_component_items WHERE component_id = 1 ORDER BY display_order").fetchall()
    assert [row["item_name"] for row in items] == ["Item 1", "Item 1.5", "Item 2", "Item 3"]

    # 3. Add like source (cloning) after relative
    resp = client.post(f"/chat/sessions/{session_id}/messages", json={
        "message": "add a new item called Item 1.6 like the Item 1 item after the Item 1.5 item",
        "campaign_id": 1
    })
    assert resp.status_code == 200
    
    with connect_database(config) as connection:
        item = connection.execute("SELECT item_name, item_value FROM campaign_component_items WHERE item_name = 'Item 1.6'").fetchone()
        assert item["item_value"] == "$10"  # Cloned from Item 1
        items = connection.execute("SELECT item_name FROM campaign_component_items WHERE component_id = 1 ORDER BY display_order").fetchall()
    assert [row["item_name"] for row in items] == ["Item 1", "Item 1.5", "Item 1.6", "Item 2", "Item 3"]

def test_chat_message_can_add_new_item_with_an_item_and_no_name(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_massage_component_items_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={
            "campaign_id": campaign_id,
            "message": "add an item to the community-appreciation component after the Swedish Massage item",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component_item"
    assert payload["result"]["field"] == "add"
    assert payload["result"]["item"]["item_name"] == "New Item"
    assert payload["result"]["item"]["display_order"] == 2

def test_chat_message_can_delete_campaign(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)

    session_id = client.post("/chat/sessions").json()["session_id"]
    
    # Delete by name
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "delete campaign Summer"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["target"] == "campaign"
    assert response.json()["result"]["field"] == "delete"

    # Verify campaign is gone
    resp = client.get(f"/businesses/1/campaigns/{campaign_id}")
    assert resp.status_code == 404

def test_chat_message_can_add_component(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)

    session_id = client.post("/chat/sessions").json()["session_id"]
    
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "add new component called Weekend Specials of type weekday-specials"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["target"] == "component"
    assert response.json()["result"]["field"] == "add"
    assert response.json()["result"]["component_key"] == "weekend-specials"

def test_chat_message_can_update_component_style(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)
    _seed_component_for_campaign(campaign_id)

    session_id = client.post("/chat/sessions").json()["session_id"]
    
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set mothers-day-specials style border_radius to 20"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["target"] == "component"
    assert response.json()["result"]["field"] == "style_json"
    assert response.json()["result"]["style"]["border_radius"] == "20"


def test_chat_message_can_update_component_style_by_unique_kind(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)

    config = resolve_config()
    with connect_database(config) as connection:
        connection.execute(
            """
            INSERT INTO campaign_components (
              campaign_id, component_key, component_kind, display_title, display_order
            )
            VALUES (?, 'discount-panel', 'discount-strip', 'Discount Panel', 1);
            """,
            (campaign_id,),
        )
        connection.commit()

    session_id = client.post("/chat/sessions").json()["session_id"]

    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "set discount-strip style item_price_color to #181818"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["target"] == "component"
    assert payload["result"]["field"] == "style_json"
    assert payload["result"]["component_key"] == "discount-panel"
    assert payload["result"]["style"]["item_price_color"] == "#181818"


def test_chat_message_can_manage_offers(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    client = _make_client(monkeypatch, config_path)
    _, campaign_id = _seed_campaign(client)

    session_id = client.post("/chat/sessions").json()["session_id"]
    
    # 1. Add Offer
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": "add new offer called early-bird"},
    )
    assert response.status_code == 200
    offer_id = response.json()["result"]["id"]

    # 2. Delete Offer
    response = client.post(
        f"/chat/sessions/{session_id}/messages",
        json={"campaign_id": campaign_id, "message": f"delete offer {offer_id}"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["deleted"] is True
