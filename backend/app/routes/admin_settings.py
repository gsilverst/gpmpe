from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..config import resolve_config
from ..dependencies import get_db_session
from ..schemas import RuntimeGitSettingsRequest, RuntimeGitSettingsResponse
from ..services.runtime_settings import (
    get_runtime_git_settings,
    list_admin_audit_logs,
    upsert_runtime_git_settings,
)
from ..services.secret_store import SecretStoreError

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/git-settings", response_model=RuntimeGitSettingsResponse)
def read_git_settings(db: Session = Depends(get_db_session)) -> RuntimeGitSettingsResponse:
    return get_runtime_git_settings(db, resolve_config())


@router.put("/git-settings", response_model=RuntimeGitSettingsResponse)
def update_git_settings(
    payload: RuntimeGitSettingsRequest,
    db: Session = Depends(get_db_session),
    x_gpmpe_actor: str | None = Header(default=None),
) -> RuntimeGitSettingsResponse:
    actor = (x_gpmpe_actor or "system").strip() or "system"
    try:
        return upsert_runtime_git_settings(db, resolve_config(), payload, actor=actor)
    except SecretStoreError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/audit-logs")
def read_audit_logs(
    limit: int = 25,
    db: Session = Depends(get_db_session),
) -> dict[str, object]:
    bounded_limit = max(1, min(limit, 100))
    return {"items": list_admin_audit_logs(db, limit=bounded_limit)}
