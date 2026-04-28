from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from .conftest import enable_test_paths, write_isolated_config


def test_health_returns_ok_and_output_dir(monkeypatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    config_path = write_isolated_config(
        tmp_path,
        output_dir=output_dir,
        test_data_dir=tmp_path / "yaml-data-test",
    )
    enable_test_paths(monkeypatch, config_path)

    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database"] == "ok"
    assert payload["output_dir"] == str(output_dir.resolve())
