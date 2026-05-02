from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import AppConfig
from ..models import AdminAuditLog, RuntimeGitSettings
from ..schemas import RuntimeGitSettingsRequest, RuntimeGitSettingsResponse
from .secret_store import SecretStoreError, secret_store_for_config


GLOBAL_SCOPE = "global"


@dataclass(frozen=True)
class EffectiveGitSettings:
    repo_path: Path | None
    user_name: str | None
    user_email: str | None
    push_enabled: bool
    remote: str
    branch: str
    lock_timeout_seconds: float
    source: str


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _settings_response(config: AppConfig, settings: RuntimeGitSettings | None) -> RuntimeGitSettingsResponse:
    if settings is None:
        return RuntimeGitSettingsResponse(
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
        scope=settings.scope,
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


def upsert_runtime_git_settings(
    db: Session,
    config: AppConfig,
    payload: RuntimeGitSettingsRequest,
    *,
    actor: str,
) -> RuntimeGitSettingsResponse:
    settings = db.query(RuntimeGitSettings).filter(RuntimeGitSettings.scope == GLOBAL_SCOPE).first()
    if settings is None:
        settings = RuntimeGitSettings(scope=GLOBAL_SCOPE)
        db.add(settings)

    credential_reference = _clean_optional(payload.credential_reference)
    if payload.credential_secret is not None:
        if credential_reference is None:
            credential_reference = f"gpmpe/{config.run_mode}/git/global"
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
            scope=GLOBAL_SCOPE,
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
    return _settings_response(config, settings)


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


def effective_git_settings(db: Session, config: AppConfig) -> EffectiveGitSettings:
    settings = db.query(RuntimeGitSettings).filter(RuntimeGitSettings.scope == GLOBAL_SCOPE).first()
    if settings is None:
        return EffectiveGitSettings(
            repo_path=config.git_repo_path,
            user_name=config.git_user_name,
            user_email=config.git_user_email,
            push_enabled=config.git_push_enabled,
            remote=config.git_remote,
            branch=config.git_branch,
            lock_timeout_seconds=config.git_lock_timeout_seconds,
            source="config",
        )

    return EffectiveGitSettings(
        repo_path=Path(settings.repo_path).expanduser().resolve() if settings.repo_path else None,
        user_name=settings.user_name,
        user_email=settings.user_email,
        push_enabled=settings.push_enabled,
        remote=settings.remote_name,
        branch=settings.branch,
        lock_timeout_seconds=config.git_lock_timeout_seconds,
        source="database",
    )
