from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from app.config import resolve_config
from app.data_sync import discover_data_directory, sync_data_directory
from app.db import connect_database, initialize_database
from app.main import create_app


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sample_data_dir() -> Path:
    return _repo_root() / "tests" / "data"


def _write_config(tmp_path: Path, data_dir: Path) -> Path:
    config_path = tmp_path / ".config"
    output_dir = tmp_path / "output"
    database_path = tmp_path / "data" / "test.db"
    config_path.write_text(
        f"OUTPUT_DIR={output_dir}\nDATABASE_PATH={database_path}\nDATA_DIR={data_dir}\n",
        encoding="utf-8",
    )
    return config_path


def test_discover_data_directory_reads_sample_tree() -> None:
    records = discover_data_directory(_sample_data_dir())

    assert len(records) == 1
    assert records[0].directory_name == "acme"
    assert records[0].campaigns[0].directory_name == "mothersday"


def test_discover_data_directory_rejects_unsafe_names(tmp_path: Path) -> None:
    unsafe_business = tmp_path / "Sample Sales"
    unsafe_business.mkdir(parents=True, exist_ok=True)
    (unsafe_business / "Sample Sales.yaml").write_text("display_name: Sample Sales\nlegal_name: Sample Sales LLC\n", encoding="utf-8")

    try:
        discover_data_directory(tmp_path)
    except ValueError as error:
        assert "Unsafe business name" in str(error)
    else:
        raise AssertionError("Expected unsafe business name error")


def test_sync_data_directory_populates_database(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, _sample_data_dir())
    monkeypatch.setenv("GPMPG_CONFIG_FILE", str(config_path))
    config = resolve_config(repo_root=_repo_root(), cwd=_repo_root())

    initialize_database(config)
    with connect_database(config) as connection:
        summary = sync_data_directory(connection, config.data_dir)
        connection.commit()

        business = connection.execute(
            "SELECT display_name, legal_name FROM businesses WHERE display_name = 'acme';"
        ).fetchone()
        campaign = connection.execute(
            "SELECT campaign_name, campaign_key, title FROM campaigns WHERE campaign_name = 'mothersday';"
        ).fetchone()

    assert summary.businesses_synced == 1
    assert summary.campaigns_synced == 1
    assert business is not None
    assert business["legal_name"] == "Acme Promotions LLC"
    assert campaign is not None
    assert campaign["campaign_key"] == ""
    assert campaign["title"] == "Mother's Day Appreciation Sale"


def test_data_manager_api_reads_synced_sample_data(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, _sample_data_dir())
    monkeypatch.setenv("GPMPG_CONFIG_FILE", str(config_path))

    with TestClient(create_app()) as client:
        businesses = client.get("/data-manager/businesses")
        assert businesses.status_code == 200
        assert businesses.json()["items"][0]["display_name"] == "acme"

        business_detail = client.get("/data-manager/businesses/acme")
        assert business_detail.status_code == 200
        assert business_detail.json()["brand_theme"]["primary_color"] == "#209dd7"

        campaigns = client.get("/data-manager/businesses/acme/campaigns")
        assert campaigns.status_code == 200
        assert campaigns.json()["items"][0]["campaign_name"] == "mothersday"

        campaign_detail = client.get("/data-manager/businesses/acme/campaigns/mothersday")
        assert campaign_detail.status_code == 200
        payload = campaign_detail.json()
        assert payload["business"]["display_name"] == "acme"
        assert payload["campaign"]["template_binding"]["template_name"] == "flyer-standard"
        assert payload["campaign"]["offers"][0]["offer_name"] == "flower-bundle"


def test_sync_data_directory_removes_stale_businesses_and_campaigns(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, _sample_data_dir())
    monkeypatch.setenv("GPMPG_CONFIG_FILE", str(config_path))
    config = resolve_config(repo_root=_repo_root(), cwd=_repo_root())

    initialize_database(config)
    with connect_database(config) as connection:
        sync_data_directory(connection, config.data_dir)

        acme_business = connection.execute(
            "SELECT id FROM businesses WHERE display_name = 'acme';"
        ).fetchone()
        assert acme_business is not None

        stale_business_id = connection.execute(
            "INSERT INTO businesses (legal_name, display_name, timezone) VALUES (?, ?, ?);",
            ("Legacy Promotions LLC", "legacy", "America/New_York"),
        ).lastrowid
        connection.execute(
            "INSERT INTO campaigns (business_id, campaign_name, campaign_key, title) VALUES (?, ?, ?, ?);",
            (stale_business_id, "clearance", "", "Legacy Clearance"),
        )

        stale_campaign_id = connection.execute(
            "INSERT INTO campaigns (business_id, campaign_name, campaign_key, title) VALUES (?, ?, ?, ?);",
            (acme_business["id"], "winter-sale", "", "Winter Sale"),
        ).lastrowid
        stale_template_id = connection.execute(
            "INSERT INTO template_definitions (template_name, template_kind) VALUES (?, ?);",
            ("legacy-template", "flyer"),
        ).lastrowid
        connection.execute(
            "INSERT INTO campaign_template_bindings (campaign_id, template_id, override_values_json, is_active) VALUES (?, ?, ?, 1);",
            (stale_campaign_id, stale_template_id, "{}"),
        )
        connection.commit()

        sync_data_directory(connection, config.data_dir)
        connection.commit()

        remaining_businesses = connection.execute(
            "SELECT display_name FROM businesses ORDER BY display_name ASC;"
        ).fetchall()
        remaining_campaigns = connection.execute(
            "SELECT campaign_name FROM campaigns WHERE business_id = ? ORDER BY campaign_name ASC;",
            (acme_business["id"],),
        ).fetchall()
        orphan_template = connection.execute(
            "SELECT id FROM template_definitions WHERE template_name = 'legacy-template';"
        ).fetchone()

    assert [row["display_name"] for row in remaining_businesses] == ["acme"]
    assert [row["campaign_name"] for row in remaining_campaigns] == ["mothersday"]
    assert orphan_template is None


def test_sync_data_directory_persists_components_and_export_round_trips(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "component-data"
    business_dir = data_dir / "beacon"
    campaign_dir = business_dir / "spring-refresh"
    campaign_dir.mkdir(parents=True, exist_ok=True)
    (business_dir / "beacon.yaml").write_text(
        "display_name: beacon\nlegal_name: Beacon Wellness LLC\ntimezone: America/New_York\n",
        encoding="utf-8",
    )
    (campaign_dir / "spring-refresh.yaml").write_text(
        "\n".join(
            [
                "display_name: spring-refresh",
                "campaign_name: spring-refresh",
                "title: Spring Refresh",
                "objective: Drive bookings",
                "status: active",
                "components:",
                "  - component_key: featured",
                "    component_kind: featured-offers",
                "    display_title: Featured Services",
                "    subtitle: Limited time",
                "    description_text: Seasonal appointment highlights",
                "    items:",
                "      - item_name: Signature Facial",
                "        item_kind: service",
                "        duration_label: 60 min",
                "        item_value: $95",
                "        description_text: Includes exfoliation",
                "        terms_text: By appointment only",
                "  - component_key: notes",
                "    component_kind: legal-note",
                "    display_title: Promotion Notes",
                "    items:",
                "      - item_name: Offer valid through April 30",
                "        item_kind: promo-note",
                "        item_value: See spa for details",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config_path = _write_config(tmp_path, data_dir)
    monkeypatch.setenv("GPMPG_CONFIG_FILE", str(config_path))
    config = resolve_config(repo_root=_repo_root(), cwd=_repo_root())

    initialize_database(config)
    with connect_database(config) as connection:
        sync_data_directory(connection, config.data_dir)
        connection.commit()

        components = connection.execute(
            """
            SELECT component_key, component_kind, display_title, subtitle, description_text, display_order
            FROM campaign_components
            ORDER BY display_order ASC, id ASC;
            """
        ).fetchall()
        items = connection.execute(
            """
            SELECT item_name, item_kind, duration_label, item_value, description_text, terms_text, display_order
            FROM campaign_component_items
            ORDER BY display_order ASC, id ASC;
            """
        ).fetchall()

        client = TestClient(create_app())
        campaign_detail = client.get("/data-manager/businesses/beacon/campaigns/spring-refresh")

    assert [row["component_key"] for row in components] == ["featured", "notes"]
    assert components[0]["display_title"] == "Featured Services"
    assert items[0]["item_name"] == "Signature Facial"
    assert items[0]["duration_label"] == "60 min"
    assert campaign_detail.status_code == 200
    payload = campaign_detail.json()["campaign"]
    assert payload["components"][0]["component_key"] == "featured"
    assert payload["components"][0]["items"][0]["item_value"] == "$95"
