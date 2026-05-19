from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import AppConfig
from ..models import AdminAuditLog, AppMeta, RuntimeGitSettings
from ..schemas import (
    AdminAppSettingsRequest,
    AdminAppSettingsResponse,
    RuntimeGitSettingsRequest,
    RuntimeGitSettingsResponse,
)
from .secret_store import SecretStoreError, secret_store_for_config


GLOBAL_SCOPE = "global"
DEFAULT_PROMOTION_TYPE_KEY = "default_promotion_type"
PROMOTION_TYPES = {"sales", "storybook"}


@dataclass(frozen=True)
class EffectiveGitSettings:
    repo_path: Path | None
    user_name: str | None
    user_email: str | None
    push_enabled: bool
    remote: str
    remote_url: str | None
    branch: str
    lock_timeout_seconds: float
    credential_secret: str | None
    source: str


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_promotion_type(value: str | None) -> str:
    normalized = (value or "sales").strip().lower()
    return normalized if normalized in PROMOTION_TYPES else "sales"


def _business_scope(business_id: int) -> str:
    return f"business:{business_id}"


def _default_credential_reference(config: AppConfig, scope: str) -> str:
    if scope == GLOBAL_SCOPE:
        return f"gpmpe/{config.run_mode}/git/global"
    return f"gpmpe/{config.run_mode}/git/{scope.replace(':', '-')}"


def _settings_response(
    config: AppConfig,
    settings: RuntimeGitSettings | None,
    *,
    scope: str = GLOBAL_SCOPE,
    source: str | None = None,
) -> RuntimeGitSettingsResponse:
    if settings is None:
        return RuntimeGitSettingsResponse(
            scope=scope,
            source=source or "config",
            repo_path=str(config.git_repo_path) if config.git_repo_path else None,
            remote_url=None,
            remote_name=config.git_remote,
            branch=config.git_branch,
            user_name=config.git_user_name,
            user_email=config.git_user_email,
            push_enabled=config.git_push_enabled,
            credential_provider="local",
            credential_reference=None,
            credential_configured=False,
            updated_at=None,
        )

    credential_configured = False
    if settings.credential_reference:
        try:
            credential_configured = secret_store_for_config(config, settings.credential_provider).has_secret(
                settings.credential_reference
            )
        except SecretStoreError:
            credential_configured = False

    return RuntimeGitSettingsResponse(
        scope=scope,
        source=source or "database",
        repo_path=settings.repo_path,
        remote_url=settings.remote_url,
        remote_name=settings.remote_name,
        branch=settings.branch,
        user_name=settings.user_name,
        user_email=settings.user_email,
        push_enabled=settings.push_enabled,
        credential_provider=settings.credential_provider,
        credential_reference=settings.credential_reference,
        credential_configured=credential_configured,
        updated_at=settings.updated_at.isoformat() if settings.updated_at else None,
    )


def get_runtime_git_settings(db: Session, config: AppConfig) -> RuntimeGitSettingsResponse:
    settings = db.query(RuntimeGitSettings).filter(RuntimeGitSettings.scope == GLOBAL_SCOPE).first()
    return _settings_response(config, settings)


def get_admin_app_settings(db: Session) -> AdminAppSettingsResponse:
    row = db.query(AppMeta).filter(AppMeta.key == DEFAULT_PROMOTION_TYPE_KEY).first()
    return AdminAppSettingsResponse(
        default_promotion_type=_normalize_promotion_type(row.value if row else None),  # type: ignore[arg-type]
        updated_at=None,
    )


def upsert_admin_app_settings(
    db: Session,
    payload: AdminAppSettingsRequest,
    *,
    actor: str,
) -> AdminAppSettingsResponse:
    promotion_type = _normalize_promotion_type(payload.default_promotion_type)
    row = db.query(AppMeta).filter(AppMeta.key == DEFAULT_PROMOTION_TYPE_KEY).first()
    if row is None:
        row = AppMeta(key=DEFAULT_PROMOTION_TYPE_KEY, value=promotion_type)
        db.add(row)
    else:
        row.value = promotion_type

    db.add(
        AdminAuditLog(
            actor=actor,
            action="admin_app_settings.update",
            scope=GLOBAL_SCOPE,
            metadata_json=json.dumps(
                {"default_promotion_type": promotion_type},
                sort_keys=True,
            ),
        )
    )
    db.commit()
    return AdminAppSettingsResponse(default_promotion_type=promotion_type, updated_at=None)


def get_business_git_settings(db: Session, config: AppConfig, business_id: int) -> RuntimeGitSettingsResponse:
    business_scope = _business_scope(business_id)
    settings = db.query(RuntimeGitSettings).filter(RuntimeGitSettings.scope == business_scope).first()
    if settings is not None:
        return _settings_response(config, settings, scope=business_scope, source="business")

    global_settings = db.query(RuntimeGitSettings).filter(RuntimeGitSettings.scope == GLOBAL_SCOPE).first()
    if global_settings is not None:
        return _settings_response(config, global_settings, scope=business_scope, source="global")

    return _settings_response(config, None, scope=business_scope, source="config")


def upsert_runtime_git_settings(
    db: Session,
    config: AppConfig,
    payload: RuntimeGitSettingsRequest,
    *,
    actor: str,
) -> RuntimeGitSettingsResponse:
    return upsert_git_settings_for_scope(
        db,
        config,
        GLOBAL_SCOPE,
        payload,
        actor=actor,
        response_source="database",
    )


def upsert_business_git_settings(
    db: Session,
    config: AppConfig,
    business_id: int,
    payload: RuntimeGitSettingsRequest,
    *,
    actor: str,
) -> RuntimeGitSettingsResponse:
    business_scope = _business_scope(business_id)
    return upsert_git_settings_for_scope(
        db,
        config,
        business_scope,
        payload,
        actor=actor,
        response_source="business",
    )


def upsert_git_settings_for_scope(
    db: Session,
    config: AppConfig,
    scope: str,
    payload: RuntimeGitSettingsRequest,
    *,
    actor: str,
    response_source: str,
) -> RuntimeGitSettingsResponse:
    settings = db.query(RuntimeGitSettings).filter(RuntimeGitSettings.scope == scope).first()
    if settings is None:
        settings = RuntimeGitSettings(scope=scope)
        db.add(settings)

    credential_reference = _clean_optional(payload.credential_reference)
    if payload.credential_secret is not None:
        if credential_reference is None:
            credential_reference = _default_credential_reference(config, scope)
        secret_store_for_config(config, payload.credential_provider).save_secret(
            credential_reference,
            payload.credential_secret,
        )

    settings.repo_path = _clean_optional(payload.repo_path)
    settings.remote_url = _clean_optional(payload.remote_url)
    settings.remote_name = payload.remote_name.strip()
    settings.branch = payload.branch.strip()
    settings.user_name = _clean_optional(payload.user_name)
    settings.user_email = _clean_optional(payload.user_email)
    settings.push_enabled = payload.push_enabled
    settings.credential_provider = payload.credential_provider
    settings.credential_reference = credential_reference

    db.add(
        AdminAuditLog(
            actor=actor,
            action="runtime_git_settings.update",
            scope=scope,
            metadata_json=json.dumps(
                {
                    "repo_path": settings.repo_path,
                    "remote_url": settings.remote_url,
                    "remote_name": settings.remote_name,
                    "branch": settings.branch,
                    "user_name": settings.user_name,
                    "user_email": settings.user_email,
                    "push_enabled": settings.push_enabled,
                    "credential_provider": settings.credential_provider,
                    "credential_reference": settings.credential_reference,
                    "credential_secret_updated": payload.credential_secret is not None,
                },
                sort_keys=True,
            ),
        )
    )
    db.commit()
    db.refresh(settings)
    return _settings_response(config, settings, scope=scope, source=response_source)


def list_admin_audit_logs(db: Session, *, limit: int = 25) -> list[dict[str, object]]:
    rows = (
        db.query(AdminAuditLog)
        .order_by(AdminAuditLog.id.desc())
        .limit(limit)
        .all()
    )
    results: list[dict[str, object]] = []
    for row in rows:
        try:
            metadata = json.loads(row.metadata_json or "{}")
        except json.JSONDecodeError:
            metadata = {}
        results.append(
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "scope": row.scope,
                "metadata": metadata,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return results


def _credential_secret(config: AppConfig, settings: RuntimeGitSettings | None) -> str | None:
    if settings is None or not settings.credential_reference:
        return None
    return secret_store_for_config(config, settings.credential_provider).get_secret(settings.credential_reference)


def effective_git_settings(db: Session, config: AppConfig, business_id: int | None = None) -> EffectiveGitSettings:
    settings: RuntimeGitSettings | None = None
    source = "config"
    if business_id is not None:
        settings = db.query(RuntimeGitSettings).filter(RuntimeGitSettings.scope == _business_scope(business_id)).first()
        if settings is not None:
            source = "business"

    if settings is None:
        settings = db.query(RuntimeGitSettings).filter(RuntimeGitSettings.scope == GLOBAL_SCOPE).first()
        if settings is not None:
            source = "database"

    if settings is None:
        return EffectiveGitSettings(
            repo_path=config.git_repo_path,
            user_name=config.git_user_name,
            user_email=config.git_user_email,
            push_enabled=config.git_push_enabled,
            remote=config.git_remote,
            remote_url=None,
            branch=config.git_branch,
            lock_timeout_seconds=config.git_lock_timeout_seconds,
            credential_secret=None,
            source="config",
        )

    return EffectiveGitSettings(
        repo_path=Path(settings.repo_path).expanduser().resolve() if settings.repo_path else None,
        user_name=settings.user_name,
        user_email=settings.user_email,
        push_enabled=settings.push_enabled,
        remote=settings.remote_name,
        remote_url=settings.remote_url,
        branch=settings.branch,
        lock_timeout_seconds=config.git_lock_timeout_seconds,
        credential_secret=_credential_secret(config, settings),
        source=source,
    )
