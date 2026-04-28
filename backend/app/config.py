from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class AppConfig:
    config_path: Path
    output_dir: Path
    database_path: Path
    data_dir: Path
    commit_on_save: bool
    git_repo_path: Path | None
    git_user_name: str | None
    git_user_email: str | None


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value '{value}'")


def parse_key_value_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip()
    return values


def load_key_value_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return parse_key_value_text(path.read_text(encoding="utf-8"))


def _resolve_path(value: str, cwd: Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (cwd / candidate).resolve()


def resolve_config(repo_root: Path | None = None, cwd: Path | None = None) -> AppConfig:
    root = repo_root or Path(__file__).resolve().parents[2]
    working_directory = (cwd or Path.cwd()).resolve()

    override_path = os.getenv("GPMPG_CONFIG_FILE")
    config_path = Path(override_path).resolve() if override_path else (root / ".config")
    config_directory = config_path.parent.resolve()

    values = load_key_value_file(config_path)

    output_dir_value = values.get("OUTPUT_DIR")
    output_dir = _resolve_path(output_dir_value, config_directory) if output_dir_value else working_directory

    database_value = values.get("DATABASE_PATH")
    if database_value:
        database_path = _resolve_path(database_value, config_directory)
    else:
        database_path = (root / "backend" / "data" / "gpmpg.db").resolve()

    data_dir_value = values.get("DATA_DIR")
    if data_dir_value is None:
        raise ValueError("DATA_DIR must be configured in .config")
    data_dir = _resolve_path(data_dir_value, config_directory)

    commit_on_save = _parse_bool(values.get("COMMIT_ON_SAVE"), default=True)
    git_repo_value = values.get("GIT_REPO_PATH")
    git_repo_path = _resolve_path(git_repo_value, config_directory) if git_repo_value else None
    git_user_name = values.get("GIT_USER_NAME")
    git_user_email = values.get("GIT_USER_EMAIL")

    return AppConfig(
        config_path=config_path,
        output_dir=output_dir,
        database_path=database_path,
        data_dir=data_dir,
        commit_on_save=commit_on_save,
        git_repo_path=git_repo_path,
        git_user_name=git_user_name,
        git_user_email=git_user_email,
    )
