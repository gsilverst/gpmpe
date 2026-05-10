from __future__ import annotations

from dataclasses import dataclass
import base64
import json

from fastapi import Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import AppConfig, resolve_config
from ..models import AdminAuditLog, AppUser, Business, BusinessAccessGrant
from ..schemas import AdminUserInviteRequest, AdminUserResponse


ADMIN_ROLES = {"primary_admin", "admin"}
VALID_ROLES = {"primary_admin", "admin", "regular"}


def _cognito_client_factory(region_name: str | None = None):
    import boto3

    return boto3.client("cognito-idp", region_name=region_name)


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


def user_to_response(db: Session, user: AppUser) -> AdminUserResponse:
    business_ids = [
        row.business_id
        for row in db.query(BusinessAccessGrant)
        .filter(BusinessAccessGrant.user_id == user.id)
        .order_by(BusinessAccessGrant.business_id.asc())
        .all()
    ]
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        business_ids=business_ids,
        created_at=user.created_at.isoformat() if user.created_at else None,
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
    )


def list_app_users(db: Session) -> list[AdminUserResponse]:
    users = db.query(AppUser).order_by(AppUser.email.asc()).all()
    return [user_to_response(db, user) for user in users]


def _validate_invite_role(inviter: AppPrincipal, requested_role: str) -> None:
    if requested_role not in {"admin", "regular"}:
        raise HTTPException(status_code=400, detail="Unsupported role")
    if inviter.role == "admin" and requested_role != "regular":
        raise HTTPException(status_code=403, detail="Admin users may invite regular users only")
    if inviter.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Administrator access required")


def _ensure_businesses_exist(db: Session, business_ids: list[int]) -> list[int]:
    unique_ids = sorted(set(business_ids))
    if not unique_ids:
        return []
    existing_ids = {
        business.id
        for business in db.query(Business).filter(Business.id.in_(unique_ids)).all()
    }
    missing = [business_id for business_id in unique_ids if business_id not in existing_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"Business not found: {missing[0]}")
    return unique_ids


def send_cognito_invite(config: AppConfig, *, email: str, display_name: str | None) -> None:
    if not config.cognito_user_pool_id:
        if config.auth_mode == "alb_oidc":
            raise HTTPException(status_code=503, detail="COGNITO_USER_POOL_ID is not configured")
        return

    attributes = [
        {"Name": "email", "Value": email},
        {"Name": "email_verified", "Value": "false"},
    ]
    if display_name:
        attributes.append({"Name": "name", "Value": display_name})

    client = _cognito_client_factory(config.cognito_region)
    try:
        client.admin_create_user(
            UserPoolId=config.cognito_user_pool_id,
            Username=email,
            UserAttributes=attributes,
            DesiredDeliveryMediums=["EMAIL"],
        )
    except client.exceptions.UsernameExistsException as error:
        raise HTTPException(status_code=409, detail="User already exists in Cognito") from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Failed to send Cognito invite") from error


def invite_app_user(
    db: Session,
    config: AppConfig,
    payload: AdminUserInviteRequest,
    *,
    inviter: AppPrincipal,
    actor: str,
) -> AdminUserResponse:
    email = normalize_email(payload.email)
    _validate_invite_role(inviter, payload.role)

    existing = db.query(AppUser).filter(AppUser.email == email).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="User already exists")

    business_ids = _ensure_businesses_exist(db, payload.business_ids)
    if payload.role != "regular" and business_ids:
        raise HTTPException(status_code=400, detail="Business grants apply to regular users only")

    send_cognito_invite(config, email=email, display_name=payload.display_name)

    status = "invited" if config.cognito_user_pool_id else "active"
    user = AppUser(
        email=email,
        display_name=payload.display_name,
        role=payload.role,
        status=status,
    )
    db.add(user)
    db.flush()

    for business_id in business_ids:
        db.add(
            BusinessAccessGrant(
                user_id=user.id,
                business_id=business_id,
                access_level="editor",
            )
        )

    db.add(
        AdminAuditLog(
            actor=actor,
            action="auth.user_invite",
            scope="global",
            metadata_json=json.dumps(
                {
                    "email": email,
                    "role": payload.role,
                    "status": status,
                    "business_ids": business_ids,
                    "cognito_invite_sent": bool(config.cognito_user_pool_id),
                },
                sort_keys=True,
            ),
        )
    )
    db.commit()
    db.refresh(user)
    return user_to_response(db, user)


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
    if user.status not in {"active", "invited"}:
        raise HTTPException(status_code=403, detail="User is not active")

    if user.status == "invited":
        user.status = "active"
    if external_subject and user.external_subject is None:
        user.external_subject = external_subject
    if db.is_modified(user):
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
