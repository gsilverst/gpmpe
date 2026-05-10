from __future__ import annotations

import base64
import json
from pathlib import Path

from .conftest import make_test_client, write_isolated_config


def _unsigned_oidc_data(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


def test_auth_status_disabled_by_default(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    config_path = write_isolated_config(tmp_path, test_data_dir=data_dir)

    with make_test_client(monkeypatch, config_path) as client:
        response = client.get("/auth/status")
        me = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["bootstrap_required"] is False
    assert me.status_code == 200
    assert me.json()["role"] == "primary_admin"
    assert me.json()["authenticated"] is False


def test_auth_bootstrap_creates_primary_admin(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    config_path = write_isolated_config(
        tmp_path,
        test_data_dir=data_dir,
        auth_mode="dev_header",
        auth_bootstrap_token="setup-token",
    )

    with make_test_client(monkeypatch, config_path) as client:
        status_before = client.get("/auth/status")
        forbidden = client.post(
            "/auth/bootstrap",
            headers={"X-GPMPE-Setup-Token": "wrong"},
            json={"primary_admin_email": "Admin@Example.com", "display_name": "Admin"},
        )
        created = client.post(
            "/auth/bootstrap",
            headers={"X-GPMPE-Setup-Token": "setup-token"},
            json={"primary_admin_email": "Admin@Example.com", "display_name": "Admin"},
        )
        status_after = client.get("/auth/status")

    assert status_before.status_code == 200
    assert status_before.json()["bootstrap_required"] is True
    assert forbidden.status_code == 403
    assert created.status_code == 200
    assert created.json()["email"] == "admin@example.com"
    assert created.json()["role"] == "primary_admin"
    assert status_after.json()["bootstrap_required"] is False


def test_admin_routes_require_authorized_user_when_auth_enabled(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    config_path = write_isolated_config(
        tmp_path,
        test_data_dir=data_dir,
        auth_mode="dev_header",
        auth_bootstrap_token="setup-token",
    )

    with make_test_client(monkeypatch, config_path) as client:
        client.post(
            "/auth/bootstrap",
            headers={"X-GPMPE-Setup-Token": "setup-token"},
            json={"primary_admin_email": "admin@example.com"},
        )
        missing = client.get("/admin/git-settings")
        unknown = client.get(
            "/admin/git-settings",
            headers={"X-GPMPE-Dev-User-Email": "other@example.com"},
        )
        allowed = client.get(
            "/admin/git-settings",
            headers={"X-GPMPE-Dev-User-Email": "admin@example.com"},
        )

    assert missing.status_code == 401
    assert unknown.status_code == 403
    assert allowed.status_code == 200


def test_alb_oidc_identity_maps_to_app_user(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    config_path = write_isolated_config(
        tmp_path,
        test_data_dir=data_dir,
        auth_mode="alb_oidc",
        auth_bootstrap_token="setup-token",
    )

    oidc_data = _unsigned_oidc_data({"email": "admin@example.com", "name": "Admin User", "sub": "abc123"})

    with make_test_client(monkeypatch, config_path) as client:
        client.post(
            "/auth/bootstrap",
            headers={"X-GPMPE-Setup-Token": "setup-token"},
            json={"primary_admin_email": "admin@example.com"},
        )
        me = client.get("/auth/me", headers={"X-Amzn-Oidc-Data": oidc_data})

    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    assert me.json()["email"] == "admin@example.com"
    assert me.json()["role"] == "primary_admin"
