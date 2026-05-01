from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class AppConfig:
    config_path: Path
    output_dir: Path
    database_path: Path
    database_url: str
    data_dir: Path
    images_per_page: int | None
    using_test_paths: bool
    commit_on_save: bool
    git_repo_path: Path | None
    git_user_name: str | None
    git_user_email: str | None
    git_push_enabled: bool = False
    git_remote: str = "origin"
    git_branch: str = "HEAD"
    git_lock_timeout_seconds: float = 30.0
    openrouter_api_key: str | None = None


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


def _config_value(values: dict[str, str], key: str) -> str | None:
    value = os.getenv(key)
    if value is not None:
        return value
    return values.get(key)


def _use_test_paths_flag(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    return _parse_bool(os.getenv("GPMPE_USE_TEST_PATHS"), default=False)


def _parse_images_per_page(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("IMAGES_PER_PAGE must be an integer") from exc
    if parsed < 2:
        raise ValueError("IMAGES_PER_PAGE must be >= 2")
    return parsed


def _parse_positive_float(value: str | None, *, default: float, key: str) -> float:
    if value is None or value.strip() == "":
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be a positive number") from exc
    if parsed <= 0:
        raise ValueError(f"{key} must be a positive number")
    return parsed


def resolve_config(
    repo_root: Path | None = None,
    cwd: Path | None = None,
    use_test_paths: bool | None = None,
) -> AppConfig:
    root = repo_root or Path(__file__).resolve().parents[2]
    working_directory = (cwd or Path.cwd()).resolve()

    override_path = os.getenv("GPMPE_CONFIG_FILE")
    config_path = Path(override_path).resolve() if override_path else (root / ".config")
    config_directory = config_path.parent.resolve()

    values = load_key_value_file(config_path)

    output_dir_value = _config_value(values, "OUTPUT_DIR")
    output_dir = _resolve_path(output_dir_value, config_directory) if output_dir_value else working_directory

    database_value = _config_value(values, "DATABASE_PATH")
    data_dir_value = _config_value(values, "DATA_DIR")
    if data_dir_value is None:
        raise ValueError("DATA_DIR must be configured in .config")

    using_test_paths = _use_test_paths_flag(use_test_paths)
    test_database_value = _config_value(values, "TEST_DATABASE_PATH")
    test_data_dir_value = _config_value(values, "TEST_DATA_DIR")

    if using_test_paths:
        if not test_database_value or not test_data_dir_value:
            raise ValueError("TEST_DATABASE_PATH and TEST_DATA_DIR must both be configured when test paths are enabled")
        database_path = _resolve_path(test_database_value, config_directory)
        data_dir = _resolve_path(test_data_dir_value, config_directory)
    else:
        if database_value:
            database_path = _resolve_path(database_value, config_directory)
        else:
            database_path = (root / "backend" / "data" / "gpmpe.db").resolve()
        data_dir = _resolve_path(data_dir_value, config_directory)

    images_per_page = _parse_images_per_page(_config_value(values, "IMAGES_PER_PAGE"))

    database_url = _config_value(values, "DATABASE_URL")
    if not database_url:
        database_url = f"sqlite:///{database_path}"

    commit_on_save = _parse_bool(_config_value(values, "COMMIT_ON_SAVE"), default=True)
    git_repo_value = _config_value(values, "GIT_REPO_PATH")
    git_repo_path = _resolve_path(git_repo_value, config_directory) if git_repo_value else None
    git_user_name = _config_value(values, "GIT_USER_NAME")
    git_user_email = _config_value(values, "GIT_USER_EMAIL")
    git_push_enabled = _parse_bool(_config_value(values, "GIT_PUSH_ENABLED"), default=False)
    git_remote = _config_value(values, "GIT_REMOTE") or "origin"
    git_branch = _config_value(values, "GIT_BRANCH") or "HEAD"
    git_lock_timeout_seconds = _parse_positive_float(
        _config_value(values, "GIT_LOCK_TIMEOUT_SECONDS"),
        default=30.0,
        key="GIT_LOCK_TIMEOUT_SECONDS",
    )

    return AppConfig(
        config_path=config_path,
        output_dir=output_dir,
        database_path=database_path,
        database_url=database_url,
        data_dir=data_dir,
        images_per_page=images_per_page,
        using_test_paths=using_test_paths,
        commit_on_save=commit_on_save,
        git_repo_path=git_repo_path,
        git_user_name=git_user_name,
        git_user_email=git_user_email,
        git_push_enabled=git_push_enabled,
        git_remote=git_remote,
        git_branch=git_branch,
        git_lock_timeout_seconds=git_lock_timeout_seconds,
        openrouter_api_key=_config_value(values, "OPENROUTER_API_KEY") or None,
    )
