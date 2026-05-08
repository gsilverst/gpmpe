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


def test_admin_business_git_settings_inherit_global_until_overridden(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    config_path = write_isolated_config(tmp_path, test_data_dir=data_dir)

    with make_test_client(monkeypatch, config_path) as client:
        business = client.post(
            "/businesses",
            json={
                "legal_name": "Merci LLC",
                "display_name": "merci",
                "timezone": "America/New_York",
            },
        )
        global_settings = client.put(
            "/admin/git-settings",
            json={
                "repo_path": str(data_dir / "global"),
                "remote_url": "git@example.com:org/global.git",
                "remote_name": "origin",
                "branch": "main",
                "user_name": "Global Service",
                "user_email": "global@example.com",
                "push_enabled": False,
                "credential_provider": "local",
                "credential_reference": "gpmpe/local/git/global",
            },
        )
        inherited = client.get(f"/admin/businesses/{business.json()['id']}/git-settings")

    assert business.status_code == 201
    assert global_settings.status_code == 200
    assert inherited.status_code == 200
    payload = inherited.json()
    assert payload["scope"] == f"business:{business.json()['id']}"
    assert payload["source"] == "global"
    assert payload["remote_url"] == "git@example.com:org/global.git"
    assert payload["user_email"] == "global@example.com"


def test_admin_business_git_settings_save_secret_and_audit(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    config_path = write_isolated_config(tmp_path, test_data_dir=data_dir)

    with make_test_client(monkeypatch, config_path) as client:
        business = client.post(
            "/businesses",
            json={
                "legal_name": "Merci LLC",
                "display_name": "merci",
                "timezone": "America/New_York",
            },
        )
        business_id = business.json()["id"]
        response = client.put(
            f"/admin/businesses/{business_id}/git-settings",
            headers={"X-GPMPE-Actor": "business-admin"},
            json={
                "repo_path": str(data_dir / "merci"),
                "remote_url": "git@example.com:org/merci.git",
                "remote_name": "origin",
                "branch": "main",
                "user_name": "Merci Service",
                "user_email": "merci-service@example.com",
                "push_enabled": True,
                "credential_provider": "local",
                "credential_secret": "business-token",
            },
        )
        audit_response = client.get("/admin/audit-logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == f"business:{business_id}"
    assert payload["source"] == "business"
    assert payload["remote_url"] == "git@example.com:org/merci.git"
    assert payload["push_enabled"] is True
    assert payload["credential_reference"] == f"gpmpe/local/git/business-{business_id}"
    assert payload["credential_configured"] is True
    assert "business-token" not in json.dumps(payload)

    secret_payload = json.loads((tmp_path / ".gpmpe-secrets.json").read_text(encoding="utf-8"))
    assert secret_payload[f"gpmpe/local/git/business-{business_id}"] == "business-token"

    audit_items = audit_response.json()["items"]
    assert audit_items[0]["actor"] == "business-admin"
    assert audit_items[0]["scope"] == f"business:{business_id}"
    assert audit_items[0]["metadata"]["credential_secret_updated"] is True
