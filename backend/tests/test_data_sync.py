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
    assert records[0].directory_name == "merci"
    assert records[0].campaigns[0].directory_name == "mothersday"


def test_discover_data_directory_rejects_unsafe_names(tmp_path: Path) -> None:
    unsafe_business = tmp_path / "Merci Sales"
    unsafe_business.mkdir(parents=True, exist_ok=True)
    (unsafe_business / "Merci Sales.yaml").write_text("display_name: Merci Sales\nlegal_name: Merci Sales LLC\n", encoding="utf-8")

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
            "SELECT display_name, legal_name FROM businesses WHERE display_name = 'merci';"
        ).fetchone()
        campaign = connection.execute(
            "SELECT campaign_name, campaign_key, title FROM campaigns WHERE campaign_name = 'mothersday';"
        ).fetchone()

    assert summary.businesses_synced == 1
    assert summary.campaigns_synced == 1
    assert business is not None
    assert business["legal_name"] == "Merci Sales LLC"
    assert campaign is not None
    assert campaign["campaign_key"] == ""
    assert campaign["title"] == "Mother's Day Appreciation Sale"


def test_data_manager_api_reads_synced_sample_data(monkeypatch, tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, _sample_data_dir())
    monkeypatch.setenv("GPMPG_CONFIG_FILE", str(config_path))

    with TestClient(create_app()) as client:
        businesses = client.get("/data-manager/businesses")
        assert businesses.status_code == 200
        assert businesses.json()["items"][0]["display_name"] == "merci"

        business_detail = client.get("/data-manager/businesses/merci")
        assert business_detail.status_code == 200
        assert business_detail.json()["brand_theme"]["primary_color"] == "#209dd7"

        campaigns = client.get("/data-manager/businesses/merci/campaigns")
        assert campaigns.status_code == 200
        assert campaigns.json()["items"][0]["campaign_name"] == "mothersday"

        campaign_detail = client.get("/data-manager/businesses/merci/campaigns/mothersday")
        assert campaign_detail.status_code == 200
        payload = campaign_detail.json()
        assert payload["business"]["display_name"] == "merci"
        assert payload["campaign"]["template_binding"]["template_name"] == "flyer-standard"
        assert payload["campaign"]["offers"][0]["offer_name"] == "flower-bundle"
