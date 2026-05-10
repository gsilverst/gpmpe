from __future__ import annotations

from dataclasses import dataclass
import base64
import json

from fastapi import Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import AppConfig, resolve_config
from ..models import AppUser


ADMIN_ROLES = {"primary_admin", "admin"}
VALID_ROLES = {"primary_admin", "admin", "regular"}


@dataclass(frozen=True)
class AppPrincipal:
    email: str | None
    display_name: str | None
    role: str | None
    status: str | None
    authenticated: bool
    auth_mode: str
    external_subject: str | None = None

    @property
    def actor(self) -> str:
        return self.email or "system"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def auth_enabled(config: AppConfig) -> bool:
    return config.auth_mode != "disabled"


def count_app_users(db: Session) -> int:
    return int(db.query(AppUser).count())


def bootstrap_required(db: Session, config: AppConfig) -> bool:
    return auth_enabled(config) and count_app_users(db) == 0


def _decode_unverified_jwt_payload(token: str) -> dict[str, object]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode((payload + padding).encode("ascii"))
        parsed = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _identity_from_alb_headers(request: Request) -> tuple[str | None, str | None, str | None]:
    oidc_data = request.headers.get("x-amzn-oidc-data")
    identity = request.headers.get("x-amzn-oidc-identity")
    if not oidc_data:
        return None, None, identity
    payload = _decode_unverified_jwt_payload(oidc_data)
    email = payload.get("email") or payload.get("cognito:username")
    name = payload.get("name") or payload.get("given_name")
    subject = payload.get("sub") or identity
    return (
        str(email).strip().lower() if email else None,
        str(name).strip() if name else None,
        str(subject).strip() if subject else None,
    )


def _identity_from_dev_headers(request: Request) -> tuple[str | None, str | None, str | None]:
    email = request.headers.get("x-gpmpe-dev-user-email")
    name = request.headers.get("x-gpmpe-dev-user-name")
    subject = request.headers.get("x-gpmpe-dev-user-subject")
    return (
        email.strip().lower() if email else None,
        name.strip() if name else None,
        subject.strip() if subject else None,
    )


def principal_from_request(
    db: Session,
    request: Request,
    config: AppConfig | None = None,
) -> AppPrincipal:
    config = config or resolve_config()
    if config.auth_mode == "disabled":
        return AppPrincipal(
            email=None,
            display_name=None,
            role="primary_admin",
            status="active",
            authenticated=False,
            auth_mode=config.auth_mode,
        )

    if config.auth_mode == "alb_oidc":
        email, display_name, external_subject = _identity_from_alb_headers(request)
    elif config.auth_mode == "dev_header":
        email, display_name, external_subject = _identity_from_dev_headers(request)
    else:
        raise HTTPException(status_code=500, detail="Unsupported auth mode")

    if not email:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = db.query(AppUser).filter(AppUser.email == normalize_email(email)).first()
    if user is None:
        raise HTTPException(status_code=403, detail="User is authenticated but not authorized for this application")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="User is not active")

    if external_subject and user.external_subject is None:
        user.external_subject = external_subject
        db.commit()
        db.refresh(user)

    return AppPrincipal(
        email=user.email,
        display_name=user.display_name or display_name,
        role=user.role,
        status=user.status,
        authenticated=True,
        auth_mode=config.auth_mode,
        external_subject=user.external_subject or external_subject,
    )


def require_admin_principal(db: Session, request: Request) -> AppPrincipal:
    principal = principal_from_request(db, request)
    if principal.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return principal


def actor_from_request(
    db: Session,
    request: Request,
    x_gpmpe_actor: str | None = Header(default=None),
) -> str:
    principal = require_admin_principal(db, request)
    if principal.authenticated:
        return principal.actor
    return (x_gpmpe_actor or "system").strip() or "system"
