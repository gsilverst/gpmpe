from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..yaml_store import (
    campaign_yaml_paths_for_id_session,
    persist_yaml_state_for_campaign_session,
)


def persist_campaign_yaml_session_or_raise(
    db: Session,
    config: Any,
    campaign_id: int,
) -> tuple[Path, Path]:
    try:
        return persist_yaml_state_for_campaign_session(db, config.data_dir, campaign_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def campaign_yaml_paths_for_session_or_raise(
    db: Session,
    config: Any,
    campaign_id: int,
) -> tuple[Path, Path]:
    try:
        return campaign_yaml_paths_for_id_session(db, config.data_dir, campaign_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
