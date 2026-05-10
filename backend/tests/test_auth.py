from __future__ import annotations

import base64
import json
from pathlib import Path

from .conftest import make_test_client, write_isolated_config


class FakeCognitoClient:
    class exceptions:
        class UsernameExistsException(Exception):
            pass

    def __init__(self) -> None:
        self.created_users: list[dict[str, object]] = []

    def admin_create_user(self, **kwargs):
        self.created_users.append(kwargs)
        return {"User": {"Username": kwargs["Username"]}}


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


def test_auth_bootstrap_sends_cognito_invite_when_configured(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    fake_cognito = FakeCognitoClient()
    monkeypatch.setattr("app.services.auth._cognito_client_factory", lambda region_name=None: fake_cognito)
    config_path = write_isolated_config(
        tmp_path,
        test_data_dir=data_dir,
        auth_mode="dev_header",
        auth_bootstrap_token="setup-token",
        cognito_user_pool_id="us-east-2_example",
        cognito_region="us-east-2",
    )

    with make_test_client(monkeypatch, config_path) as client:
        created = client.post(
            "/auth/bootstrap",
            headers={"X-GPMPE-Setup-Token": "setup-token"},
            json={"primary_admin_email": "Admin@Example.com", "display_name": "Admin"},
        )

    assert created.status_code == 200
    assert created.json()["status"] == "invited"
    assert fake_cognito.created_users[0]["UserPoolId"] == "us-east-2_example"
    assert fake_cognito.created_users[0]["Username"] == "admin@example.com"


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


def test_primary_admin_invites_regular_user_with_business_access(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    config_path = write_isolated_config(tmp_path, test_data_dir=data_dir)

    with make_test_client(monkeypatch, config_path) as client:
        business = client.post(
            "/businesses",
            json={
                "legal_name": "Acme LLC",
                "display_name": "Acme",
                "timezone": "America/New_York",
            },
        )
        invited = client.post(
            "/admin/users/invitations",
            headers={"X-GPMPE-Actor": "bootstrap-admin"},
            json={
                "email": "regular@example.com",
                "display_name": "Regular User",
                "role": "regular",
                "business_ids": [business.json()["id"]],
            },
        )
        users = client.get("/admin/users")
        audit = client.get("/admin/audit-logs")

    assert invited.status_code == 201
    payload = invited.json()
    assert payload["email"] == "regular@example.com"
    assert payload["role"] == "regular"
    assert payload["status"] == "active"
    assert payload["business_ids"] == [business.json()["id"]]
    assert users.status_code == 200
    assert users.json()["items"][0]["email"] == "regular@example.com"
    assert audit.json()["items"][0]["actor"] == "bootstrap-admin"
    assert audit.json()["items"][0]["action"] == "auth.user_invite"


def test_admin_user_cannot_invite_admin(monkeypatch, tmp_path: Path) -> None:
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
            json={"primary_admin_email": "primary@example.com"},
        )
        create_admin = client.post(
            "/admin/users/invitations",
            headers={"X-GPMPE-Dev-User-Email": "primary@example.com"},
            json={"email": "admin@example.com", "role": "admin"},
        )
        denied = client.post(
            "/admin/users/invitations",
            headers={"X-GPMPE-Dev-User-Email": "admin@example.com"},
            json={"email": "another-admin@example.com", "role": "admin"},
        )

    assert create_admin.status_code == 201
    assert denied.status_code == 403


def test_admin_invite_sends_cognito_invite_when_configured(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    fake_cognito = FakeCognitoClient()
    monkeypatch.setattr("app.services.auth._cognito_client_factory", lambda region_name=None: fake_cognito)
    config_path = write_isolated_config(
        tmp_path,
        test_data_dir=data_dir,
        auth_mode="dev_header",
        auth_bootstrap_token="setup-token",
        cognito_user_pool_id="us-east-2_example",
        cognito_region="us-east-2",
    )

    with make_test_client(monkeypatch, config_path) as client:
        client.post(
            "/auth/bootstrap",
            headers={"X-GPMPE-Setup-Token": "setup-token"},
            json={"primary_admin_email": "primary@example.com"},
        )
        invited = client.post(
            "/admin/users/invitations",
            headers={"X-GPMPE-Dev-User-Email": "primary@example.com"},
            json={"email": "regular@example.com", "display_name": "Regular", "role": "regular"},
        )

    assert invited.status_code == 201
    assert invited.json()["status"] == "invited"
    assert fake_cognito.created_users[-1]["Username"] == "regular@example.com"


def test_alb_oidc_identity_maps_to_app_user(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "data-dir"
    data_dir.mkdir()
    fake_cognito = FakeCognitoClient()
    monkeypatch.setattr("app.services.auth._cognito_client_factory", lambda region_name=None: fake_cognito)
    config_path = write_isolated_config(
        tmp_path,
        test_data_dir=data_dir,
        auth_mode="alb_oidc",
        auth_bootstrap_token="setup-token",
        cognito_user_pool_id="us-east-2_example",
        cognito_region="us-east-2",
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
