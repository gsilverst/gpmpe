from __future__ import annotations

import json
from pathlib import Path

from .conftest import make_test_client, write_isolated_config


def test_admin_git_settings_default_to_config_values(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    config_path = write_isolated_config(
        tmp_path,
        test_data_dir=data_dir,
        git_repo_path=str(data_dir),
        git_user_name="Config User",
        git_user_email="config@example.com",
    )

    with make_test_client(monkeypatch, config_path) as client:
        response = client.get("/admin/git-settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["repo_path"] == str(data_dir)
    assert payload["user_name"] == "Config User"
    assert payload["user_email"] == "config@example.com"
    assert payload["credential_configured"] is False


def test_admin_git_settings_save_metadata_secret_and_audit(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    config_path = write_isolated_config(tmp_path, test_data_dir=data_dir)

    with make_test_client(monkeypatch, config_path) as client:
        response = client.put(
            "/admin/git-settings",
            headers={"X-GPMPE-Actor": "test-admin"},
            json={
                "repo_path": str(data_dir),
                "remote_url": "git@example.com:org/data.git",
                "remote_name": "origin",
                "branch": "main",
                "user_name": "GPMPE Service",
                "user_email": "service@example.com",
                "push_enabled": True,
                "credential_provider": "local",
                "credential_reference": "gpmpe/local/git/global",
                "credential_secret": "super-secret-token",
            },
        )
        audit_response = client.get("/admin/audit-logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["repo_path"] == str(data_dir)
    assert payload["remote_url"] == "git@example.com:org/data.git"
    assert payload["branch"] == "main"
    assert payload["push_enabled"] is True
    assert payload["credential_reference"] == "gpmpe/local/git/global"
    assert payload["credential_configured"] is True
    assert "super-secret-token" not in json.dumps(payload)

    secret_payload = json.loads((tmp_path / ".gpmpe-secrets.json").read_text(encoding="utf-8"))
    assert secret_payload["gpmpe/local/git/global"] == "super-secret-token"

    assert audit_response.status_code == 200
    audit_items = audit_response.json()["items"]
    assert audit_items[0]["actor"] == "test-admin"
    assert audit_items[0]["action"] == "runtime_git_settings.update"
    assert audit_items[0]["metadata"]["credential_secret_updated"] is True
