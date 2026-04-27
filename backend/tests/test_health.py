from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok_and_output_dir(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / ".config"
    output_dir = tmp_path / "output"
    database_path = tmp_path / "data" / "test.db"
    data_dir = tmp_path / "yaml-data"
    config_path.write_text(
        f"OUTPUT_DIR={output_dir}\nDATABASE_PATH={database_path}\nDATA_DIR={data_dir}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("GPMPG_CONFIG_FILE", str(config_path))

    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert payload["output_dir"] == str(output_dir.resolve())
