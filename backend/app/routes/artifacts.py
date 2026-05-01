from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import resolve_config
from ..dependencies import get_db_session, require_campaign
from ..git_store import GitStoreError, auto_commit_paths
from ..models import GeneratedArtifact
from ..renderer import render_campaign_artifact_session
from ..schemas import ArtifactRenderRequest, ArtifactResponse, CampaignSaveRequest
from ..services.yaml_persistence import campaign_yaml_paths_for_session_or_raise

router = APIRouter()


@router.post("/campaigns/{campaign_id}/save")
def save_campaign(
    campaign_id: int,
    payload: CampaignSaveRequest | None = None,
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    request = payload or CampaignSaveRequest()
    config = resolve_config()

    require_campaign(db, campaign_id)

    if not config.commit_on_save:
        return {
            "campaign_id": campaign_id,
            "saved": False,
            "reason": "commit_on_save_disabled",
            "auto_commit": {"enabled": False, "performed": False, "commit_id": None},
        }

    if config.git_repo_path is None or not config.git_user_name or not config.git_user_email:
        return {
            "campaign_id": campaign_id,
            "saved": False,
            "reason": "git_config_incomplete",
            "auto_commit": {"enabled": True, "performed": False, "commit_id": None},
        }

    business_file: Path
    campaign_file: Path
    business_file, campaign_file = campaign_yaml_paths_for_session_or_raise(db, config, campaign_id)
    repo_root = config.git_repo_path
    default_message = f"Save campaign {campaign_id} YAML"
    commit_message = (request.commit_message or default_message).strip()
    if commit_message == "":
        raise HTTPException(status_code=400, detail="commit_message cannot be empty")
    try:
        commit_id = auto_commit_paths(
            repo_root,
            [business_file, campaign_file],
            commit_message,
            user_name=config.git_user_name,
            user_email=config.git_user_email,
            push_enabled=config.git_push_enabled,
            remote=config.git_remote,
            branch=config.git_branch,
            lock_timeout_seconds=config.git_lock_timeout_seconds,
        )
    except GitStoreError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    auto_commit_performed = commit_id != ""

    return {
        "campaign_id": campaign_id,
        "saved": auto_commit_performed,
        "files": [str(business_file), str(campaign_file)],
        "auto_commit": {
            "enabled": True,
            "performed": auto_commit_performed,
            "commit_id": commit_id or None,
            "push_enabled": config.git_push_enabled,
        },
    }


@router.post("/campaigns/{campaign_id}/render", status_code=201)
def render_artifact(
    campaign_id: int,
    payload: ArtifactRenderRequest | None = None,
    db: Session = Depends(get_db_session),
) -> list[ArtifactResponse]:
    request = payload or ArtifactRenderRequest()
    config = resolve_config()
    require_campaign(db, campaign_id)

    try:
        results = render_campaign_artifact_session(
            db,
            campaign_id,
            config.output_dir,
            artifact_type=request.artifact_type,
            data_dir=config.data_dir,
            images_per_page=config.images_per_page,
            overwrite=request.overwrite,
            custom_name=request.custom_name,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"reason": "file_exists", "message": str(exc)}) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response_items = []
    for res in results:
        artifact = db.get(GeneratedArtifact, res["id"])
        if artifact:
            response_items.append(
                ArtifactResponse(
                    id=artifact.id,
                    campaign_id=artifact.campaign_id,
                    artifact_type=artifact.artifact_type,
                    file_path=artifact.file_path,
                    checksum=artifact.checksum,
                    status=artifact.status,
                    created_at=artifact.created_at.isoformat() if artifact.created_at else None,
                )
            )
    return response_items


@router.get("/campaigns/{campaign_id}/artifacts")
def list_artifacts(campaign_id: int, db: Session = Depends(get_db_session)) -> dict[str, Any]:
    require_campaign(db, campaign_id)
    artifacts = (
        db.query(GeneratedArtifact)
        .filter(GeneratedArtifact.campaign_id == campaign_id)
        .order_by(GeneratedArtifact.created_at.desc())
        .all()
    )

    return {
        "items": [
            {
                "id": a.id,
                "campaign_id": a.campaign_id,
                "artifact_type": a.artifact_type,
                "file_path": a.file_path,
                "checksum": a.checksum,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in artifacts
        ]
    }


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: int, db: Session = Depends(get_db_session)) -> FileResponse:
    artifact = db.get(GeneratedArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    file_path = Path(artifact.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing")
    filename = file_path.name
    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=filename,
    )


@router.get("/artifacts/{artifact_id}/view")
def view_artifact(artifact_id: int, db: Session = Depends(get_db_session)) -> FileResponse:
    artifact = db.get(GeneratedArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    file_path = Path(artifact.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing")

    return FileResponse(path=str(file_path), media_type="application/pdf")
