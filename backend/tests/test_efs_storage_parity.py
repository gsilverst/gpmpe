from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.main import create_app


def test_env_configured_storage_paths_support_sync_mutation_clone_and_render(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "efs" / "data"
    output_dir = tmp_path / "efs" / "output"
    database_path = tmp_path / "efs" / "db" / "gpmpe.db"
    shutil.copytree(Path(__file__).resolve().parents[2] / "tests" / "data", data_dir)

    config_path = tmp_path / ".config"
    config_path.write_text(
        "DATA_DIR=./wrong-data\n"
        "OUTPUT_DIR=./wrong-output\n"
        "DATABASE_PATH=./wrong.db\n"
        "COMMIT_ON_SAVE=false\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("GPMPE_CONFIG_FILE", str(config_path))
    monkeypatch.delenv("GPMPE_USE_TEST_PATHS", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("DATABASE_PATH", str(database_path))

    with TestClient(create_app()) as client:
        health = client.get("/health")
        assert health.status_code == 200, health.text
        assert health.json()["output_dir"] == str(output_dir)

        sync = client.post("/data/sync")
        assert sync.status_code == 200, sync.text
        assert sync.json()["data_dir"] == str(data_dir)

        businesses = client.get("/businesses")
        assert businesses.status_code == 200, businesses.text
        acme = next(row for row in businesses.json() if row["display_name"] == "acme")

        campaigns = client.get(f"/businesses/{acme['id']}/campaigns")
        assert campaigns.status_code == 200, campaigns.text
        mothersday = next(row for row in campaigns.json()["items"] if row["campaign_name"] == "mothersday")

        updated_title = "EFS Smoke Title"
        mutation = client.patch(
            f"/businesses/{acme['id']}/campaigns/{mothersday['id']}",
            json={"title": updated_title},
        )
        assert mutation.status_code == 200, mutation.text
        mothersday_yaml = data_dir / "acme" / "mothersday" / "mothersday.yaml"
        assert yaml.safe_load(mothersday_yaml.read_text(encoding="utf-8"))["title"] == updated_title

        session_id = client.post("/chat/sessions").json()["session_id"]
        clone = client.post(
            f"/chat/sessions/{session_id}/messages",
            json={"message": "clone mothersday and rename it to efs-smoke"},
        )
        assert clone.status_code == 200, clone.text
        assert (data_dir / "acme" / "efs-smoke" / "efs-smoke.yaml").exists()

        render = client.post(
            f"/campaigns/{mothersday['id']}/render",
            json={"custom_name": "efs-smoke-render"},
        )
        assert render.status_code == 201, render.text
        artifact_path = Path(render.json()[0]["file_path"])
        assert artifact_path.parent == output_dir
        assert artifact_path.read_bytes().startswith(b"%PDF")
