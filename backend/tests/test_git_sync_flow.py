from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.main import create_app


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_commit(cwd: Path, message: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test User", "-c", "user.email=test@example.com", "commit", "-m", message],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_sync_config(tmp_path: Path, data_repo: Path) -> Path:
    config_path = tmp_path / ".config"
    config_path.write_text(
        "\n".join(
            [
                f"OUTPUT_DIR={tmp_path / 'output'}",
                f"DATABASE_PATH={tmp_path / 'runtime.db'}",
                f"DATA_DIR={data_repo}",
                f"TEST_DATABASE_PATH={tmp_path / 'test.db'}",
                f"TEST_DATA_DIR={data_repo}",
                "COMMIT_ON_SAVE=true",
                f"GIT_REPO_PATH={data_repo}",
                "GIT_USER_NAME=Test User",
                "GIT_USER_EMAIL=test@example.com",
                "GIT_PUSH_ENABLED=true",
                "GIT_REMOTE=origin",
                "GIT_BRANCH=main",
                "GIT_LOCK_TIMEOUT_SECONDS=2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def test_git_sync_flow_pulls_yaml_to_db_and_pushes_saved_edits(monkeypatch, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    data_repo = tmp_path / "efs-data-repo"
    verify_repo = tmp_path / "verify"

    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", str(source))
    shutil.copytree(Path(__file__).resolve().parents[2] / "tests" / "data", source, dirs_exist_ok=True)
    _git(source, "add", ".")
    _git_commit(source, "Seed YAML data")
    _git(source, "branch", "-M", "main")
    _git(source, "remote", "add", "origin", str(remote))
    _git(source, "push", "origin", "main")
    _git(tmp_path, "clone", "--branch", "main", str(remote), str(data_repo))

    config_path = _write_sync_config(tmp_path, data_repo)
    monkeypatch.setenv("GPMPE_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("GPMPE_USE_TEST_PATHS", "true")

    with TestClient(create_app()) as client:
        businesses = client.get("/businesses")
        assert businesses.status_code == 200, businesses.text
        acme = next(row for row in businesses.json() if row["display_name"] == "acme")

        campaigns = client.get(f"/businesses/{acme['id']}/campaigns")
        assert campaigns.status_code == 200, campaigns.text
        mothersday = next(row for row in campaigns.json()["items"] if row["campaign_name"] == "mothersday")

        inbound_title = "Inbound Git Sync Title"
        inbound_yaml_path = source / "acme" / "mothersday" / "mothersday.yaml"
        inbound_yaml = yaml.safe_load(inbound_yaml_path.read_text(encoding="utf-8"))
        inbound_yaml["title"] = inbound_title
        inbound_yaml_path.write_text(yaml.safe_dump(inbound_yaml, sort_keys=False), encoding="utf-8")
        _git(source, "add", "acme/mothersday/mothersday.yaml")
        _git_commit(source, "Update campaign from git")
        _git(source, "push", "origin", "main")

        pull = client.post("/data/pull")
        assert pull.status_code == 200, pull.text
        assert pull.json()["changed"] is True

        campaigns_after_pull = client.get(f"/businesses/{acme['id']}/campaigns")
        assert campaigns_after_pull.status_code == 200, campaigns_after_pull.text
        pulled = next(row for row in campaigns_after_pull.json()["items"] if row["id"] == mothersday["id"])
        assert pulled["title"] == inbound_title

        outbound_title = "Outbound Chatbot Save Title"
        edit = client.patch(
            f"/businesses/{acme['id']}/campaigns/{mothersday['id']}",
            json={"title": outbound_title},
        )
        assert edit.status_code == 200, edit.text

        save = client.post(
            f"/campaigns/{mothersday['id']}/save",
            json={"commit_message": "Save campaign from AWS sync flow"},
        )
        assert save.status_code == 200, save.text
        assert save.json()["auto_commit"]["push_enabled"] is True

    _git(tmp_path, "clone", "--branch", "main", str(remote), str(verify_repo))
    remote_yaml = yaml.safe_load((verify_repo / "acme" / "mothersday" / "mothersday.yaml").read_text(encoding="utf-8"))
    assert remote_yaml["title"] == outbound_title
    assert _git(verify_repo, "log", "-1", "--pretty=%B") == "Save campaign from AWS sync flow"
