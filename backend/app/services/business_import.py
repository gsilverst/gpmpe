from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from urllib.parse import unquote, urlparse
import zipfile

from sqlalchemy.orm import Session

from ..config import AppConfig
from ..data_sync import discover_business_directory, sync_business_directory_session
from ..models import AdminAuditLog, Business


class BusinessImportError(ValueError):
    pass


@dataclass(frozen=True)
class BusinessImportPreview:
    business_directory: str
    display_name: str
    legal_name: str
    campaigns: list[str]
    business_card_themes: list[str]
    directory_exists: bool
    database_business_exists: bool
    checksum: str


def _s3_client_factory():
    try:
        import boto3
    except ImportError as exc:
        raise BusinessImportError("S3 imports require boto3 to be installed") from exc
    return boto3.client("s3")


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri.strip())
    if parsed.scheme != "s3" or not parsed.netloc:
        raise BusinessImportError("s3_uri must use the format s3://bucket/key.zip")
    key = unquote(parsed.path.lstrip("/"))
    if not key:
        raise BusinessImportError("s3_uri must include an object key")
    return parsed.netloc, key


def fetch_s3_import_zip(s3_uri: str) -> bytes:
    bucket, key = _parse_s3_uri(s3_uri)
    try:
        response = _s3_client_factory().get_object(Bucket=bucket, Key=key)
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise BusinessImportError("S3 object response did not include a readable body")
        payload = body.read()
    except BusinessImportError:
        raise
    except Exception as exc:
        raise BusinessImportError(f"Unable to read S3 import package: s3://{bucket}/{key}") from exc
    if not isinstance(payload, bytes):
        raise BusinessImportError("S3 object body must be bytes")
    if not payload:
        raise BusinessImportError("S3 import package is empty")
    return payload


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def _validate_zip_member_name(name: str) -> PurePosixPath | None:
    if name.startswith("/") or name.startswith("\\"):
        raise BusinessImportError("ZIP entries must use relative paths")
    path = PurePosixPath(name)
    if not path.parts:
        return None
    if any(part in {"", ".", ".."} for part in path.parts):
        raise BusinessImportError("ZIP entries must not contain empty, current, or parent path segments")
    if path.parts[0] in {"__MACOSX", ".DS_Store"}:
        return None
    return path


def _extract_zip_to_temp(zip_bytes: bytes, temp_parent: Path) -> Path:
    zip_path = temp_parent / "business.zip"
    zip_path.write_bytes(zip_bytes)
    try:
        with zipfile.ZipFile(zip_path) as package:
            roots: set[str] = set()
            members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            for info in package.infolist():
                if _is_zip_symlink(info):
                    raise BusinessImportError("ZIP packages must not contain symlinks")
                path = _validate_zip_member_name(info.filename)
                if path is None:
                    continue
                roots.add(path.parts[0])
                members.append((info, path))

            if len(roots) != 1:
                raise BusinessImportError("ZIP package must contain exactly one business root directory")

            extract_root = temp_parent / "extract"
            extract_root.mkdir()
            for info, path in members:
                destination = extract_root / Path(*path.parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)

            return extract_root / next(iter(roots))
    except zipfile.BadZipFile as exc:
        raise BusinessImportError("Import package must be a valid ZIP file") from exc


def _preview_business_dir(db: Session, config: AppConfig, business_dir: Path, checksum: str) -> BusinessImportPreview:
    record = discover_business_directory(business_dir)
    display_name = str(record.payload.get("display_name") or "").strip()
    legal_name = str(record.payload.get("legal_name") or "").strip()
    if not display_name or not legal_name:
        raise BusinessImportError("Business YAML must include display_name and legal_name")

    business_cards_root = business_dir / "business_cards"
    business_card_themes = (
        sorted(path.name for path in business_cards_root.iterdir() if path.is_dir())
        if business_cards_root.exists()
        else []
    )
    database_business_exists = db.query(Business).filter(Business.display_name == display_name).first() is not None
    return BusinessImportPreview(
        business_directory=business_dir.name,
        display_name=display_name,
        legal_name=legal_name,
        campaigns=[
            str(record.payload.get("campaign_name") or record.directory_name)
            for record in record.campaigns
        ],
        business_card_themes=business_card_themes,
        directory_exists=(config.data_dir / business_dir.name).exists(),
        database_business_exists=database_business_exists,
        checksum=checksum,
    )


def preview_business_zip(db: Session, config: AppConfig, zip_bytes: bytes) -> BusinessImportPreview:
    if not zip_bytes:
        raise BusinessImportError("Import package is empty")
    checksum = hashlib.sha256(zip_bytes).hexdigest()
    with tempfile.TemporaryDirectory(prefix="gpmpe-business-import-") as temp_name:
        business_dir = _extract_zip_to_temp(zip_bytes, Path(temp_name))
        return _preview_business_dir(db, config, business_dir, checksum)


def _copy_business_dir(source: Path, destination: Path, *, replace: bool) -> None:
    if destination.exists():
        if not replace:
            raise BusinessImportError(f"Business directory already exists: {destination.name}")
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _audit_import(
    db: Session,
    *,
    actor: str,
    preview: BusinessImportPreview,
    source_type: str,
    source_reference: str | None,
    conflict_action: str,
    result: str,
) -> None:
    db.add(
        AdminAuditLog(
            actor=actor,
            action="business_import.import",
            scope=preview.display_name,
            metadata_json=json.dumps(
                {
                    "business_directory": preview.business_directory,
                    "display_name": preview.display_name,
                    "source_type": source_type,
                    "source_reference": source_reference,
                    "conflict_action": conflict_action,
                    "checksum": preview.checksum,
                    "campaigns": preview.campaigns,
                    "business_card_themes": preview.business_card_themes,
                    "result": result,
                },
                sort_keys=True,
            ),
        )
    )


def import_business_zip(
    db: Session,
    config: AppConfig,
    zip_bytes: bytes,
    *,
    actor: str,
    conflict_action: str = "reject",
    source_type: str = "upload",
    source_reference: str | None = None,
) -> tuple[BusinessImportPreview, dict[str, int]]:
    if conflict_action not in {"reject", "replace"}:
        raise BusinessImportError("conflict_action must be 'reject' or 'replace'")
    if not zip_bytes:
        raise BusinessImportError("Import package is empty")

    checksum = hashlib.sha256(zip_bytes).hexdigest()
    with tempfile.TemporaryDirectory(prefix="gpmpe-business-import-") as temp_name:
        business_dir = _extract_zip_to_temp(zip_bytes, Path(temp_name))
        preview = _preview_business_dir(db, config, business_dir, checksum)
        has_conflict = preview.directory_exists or preview.database_business_exists
        if has_conflict and conflict_action == "reject":
            raise BusinessImportError("Business already exists; use conflict_action=replace to replace it")

        config.data_dir.mkdir(parents=True, exist_ok=True)
        destination = config.data_dir / preview.business_directory
        _copy_business_dir(business_dir, destination, replace=conflict_action == "replace")
        summary = sync_business_directory_session(db, destination)
        _audit_import(
            db,
            actor=actor,
            preview=preview,
            source_type=source_type,
            source_reference=source_reference,
            conflict_action=conflict_action,
            result="imported",
        )
        db.commit()
        return preview, {
            "businesses_synced": summary.businesses_synced,
            "campaigns_synced": summary.campaigns_synced,
        }


def preview_business_s3_zip(db: Session, config: AppConfig, s3_uri: str) -> BusinessImportPreview:
    return preview_business_zip(db, config, fetch_s3_import_zip(s3_uri))


def import_business_s3_zip(
    db: Session,
    config: AppConfig,
    s3_uri: str,
    *,
    actor: str,
    conflict_action: str = "reject",
) -> tuple[BusinessImportPreview, dict[str, int]]:
    return import_business_zip(
        db,
        config,
        fetch_s3_import_zip(s3_uri),
        actor=actor,
        conflict_action=conflict_action,
        source_type="s3",
        source_reference=s3_uri,
    )
