from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..config import resolve_config
from ..dependencies import get_db_session
from ..schemas import BusinessImportS3Request, RuntimeGitSettingsRequest, RuntimeGitSettingsResponse
from ..services.business_import import (
    BusinessImportError,
    import_business_s3_zip,
    import_business_zip,
    preview_business_s3_zip,
    preview_business_zip,
)
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


@router.post("/business-imports/preview")
def preview_business_import(
    package: bytes = Body(..., media_type="application/zip"),
    db: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        preview = preview_business_zip(db, resolve_config(), package)
    except BusinessImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "business_directory": preview.business_directory,
        "display_name": preview.display_name,
        "legal_name": preview.legal_name,
        "campaigns": preview.campaigns,
        "business_card_themes": preview.business_card_themes,
        "directory_exists": preview.directory_exists,
        "database_business_exists": preview.database_business_exists,
        "checksum": preview.checksum,
    }


@router.post("/business-imports")
def create_business_import(
    conflict_action: str = "reject",
    package: bytes = Body(..., media_type="application/zip"),
    db: Session = Depends(get_db_session),
    x_gpmpe_actor: str | None = Header(default=None),
) -> dict[str, object]:
    actor = (x_gpmpe_actor or "system").strip() or "system"
    try:
        preview, summary = import_business_zip(
            db,
            resolve_config(),
            package,
            actor=actor,
            conflict_action=conflict_action,
        )
    except BusinessImportError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "ok": True,
        "business_directory": preview.business_directory,
        "display_name": preview.display_name,
        "campaigns": preview.campaigns,
        "business_card_themes": preview.business_card_themes,
        "checksum": preview.checksum,
        **summary,
    }


@router.post("/business-imports/s3/preview")
def preview_s3_business_import(
    payload: BusinessImportS3Request,
    db: Session = Depends(get_db_session),
) -> dict[str, object]:
    try:
        preview = preview_business_s3_zip(db, resolve_config(), payload.s3_uri)
    except BusinessImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "business_directory": preview.business_directory,
        "display_name": preview.display_name,
        "legal_name": preview.legal_name,
        "campaigns": preview.campaigns,
        "business_card_themes": preview.business_card_themes,
        "directory_exists": preview.directory_exists,
        "database_business_exists": preview.database_business_exists,
        "checksum": preview.checksum,
        "source_type": "s3",
        "source_reference": payload.s3_uri,
    }


@router.post("/business-imports/s3")
def create_s3_business_import(
    payload: BusinessImportS3Request,
    db: Session = Depends(get_db_session),
    x_gpmpe_actor: str | None = Header(default=None),
) -> dict[str, object]:
    actor = (x_gpmpe_actor or "system").strip() or "system"
    try:
        preview, summary = import_business_s3_zip(
            db,
            resolve_config(),
            payload.s3_uri,
            actor=actor,
            conflict_action=payload.conflict_action,
        )
    except BusinessImportError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "ok": True,
        "business_directory": preview.business_directory,
        "display_name": preview.display_name,
        "campaigns": preview.campaigns,
        "business_card_themes": preview.business_card_themes,
        "checksum": preview.checksum,
        "source_type": "s3",
        "source_reference": payload.s3_uri,
        **summary,
    }
