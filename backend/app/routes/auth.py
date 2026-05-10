from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import resolve_config
from ..dependencies import get_db_session
from ..models import AdminAuditLog, AppUser
from ..schemas import AuthBootstrapRequest, AuthStatusResponse, CurrentUserResponse
from ..services.auth import (
    bootstrap_required,
    count_app_users,
    normalize_email,
    principal_from_request,
    send_cognito_invite,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatusResponse)
def read_auth_status(db: Session = Depends(get_db_session)) -> AuthStatusResponse:
    config = resolve_config()
    user_count = count_app_users(db)
    return AuthStatusResponse(
        mode=config.auth_mode,
        enabled=config.auth_mode != "disabled",
        bootstrap_required=bootstrap_required(db, config),
        user_count=user_count,
    )


@router.get("/me", response_model=CurrentUserResponse)
def read_current_user(
    request: Request,
    db: Session = Depends(get_db_session),
) -> CurrentUserResponse:
    config = resolve_config()
    if config.auth_mode == "disabled":
        return CurrentUserResponse(
            authenticated=False,
            email=None,
            display_name=None,
            role="primary_admin",
            status="active",
            auth_mode=config.auth_mode,
        )
    principal = principal_from_request(db, request, config)
    return CurrentUserResponse(
        authenticated=principal.authenticated,
        email=principal.email,
        display_name=principal.display_name,
        role=principal.role,
        status=principal.status,
        auth_mode=principal.auth_mode,
    )


@router.post("/bootstrap", response_model=CurrentUserResponse)
def bootstrap_primary_admin(
    payload: AuthBootstrapRequest,
    db: Session = Depends(get_db_session),
    x_gpmpe_setup_token: str | None = Header(default=None),
) -> CurrentUserResponse:
    config = resolve_config()
    if config.auth_mode == "disabled":
        raise HTTPException(status_code=400, detail="Authentication is disabled")
    if not bootstrap_required(db, config):
        raise HTTPException(status_code=409, detail="Application has already been bootstrapped")
    if not config.auth_bootstrap_token:
        raise HTTPException(status_code=503, detail="AUTH_BOOTSTRAP_TOKEN is not configured")
    if x_gpmpe_setup_token != config.auth_bootstrap_token:
        raise HTTPException(status_code=403, detail="Invalid setup token")

    email = normalize_email(payload.primary_admin_email)
    send_cognito_invite(config, email=email, display_name=payload.display_name)
    status = "invited" if config.cognito_user_pool_id else "active"
    user = AppUser(
        email=email,
        display_name=payload.display_name,
        role="primary_admin",
        status=status,
    )
    db.add(user)
    db.add(
        AdminAuditLog(
            actor=email,
            action="auth.bootstrap_primary_admin",
            scope="global",
            metadata_json=json.dumps(
                {
                    "email": email,
                    "status": status,
                    "cognito_invite_sent": bool(config.cognito_user_pool_id),
                },
                sort_keys=True,
            ),
        )
    )
    db.commit()
    db.refresh(user)
    return CurrentUserResponse(
        authenticated=True,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        status=user.status,
        auth_mode=config.auth_mode,
    )
