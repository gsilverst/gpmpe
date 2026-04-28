from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def write_isolated_config(
    tmp_path: Path,
    *,
    test_data_dir: Path,
    runtime_data_dir: Path | None = None,
    output_dir: Path | None = None,
    runtime_database_path: Path | None = None,
    test_database_path: Path | None = None,
    commit_on_save: bool | None = None,
    git_repo_path: str | None = None,
    git_user_name: str | None = None,
    git_user_email: str | None = None,
    openrouter_api_key: str | None = None,
) -> Path:
    config_path = tmp_path / ".config"
    output_dir = output_dir or (tmp_path / "output")
    runtime_database_path = runtime_database_path or (tmp_path / "data" / "runtime.db")
    test_database_path = test_database_path or (tmp_path / "data" / "test.db")
    runtime_data_dir = runtime_data_dir or (tmp_path / "yaml-data-runtime")

    lines = [
        f"OUTPUT_DIR={output_dir}",
        f"DATABASE_PATH={runtime_database_path}",
        f"DATA_DIR={runtime_data_dir}",
        f"TEST_DATABASE_PATH={test_database_path}",
        f"TEST_DATA_DIR={test_data_dir}",
    ]

    if commit_on_save is not None:
        lines.append(f"COMMIT_ON_SAVE={'true' if commit_on_save else 'false'}")
    if git_repo_path:
        lines.append(f"GIT_REPO_PATH={git_repo_path}")
    if git_user_name:
        lines.append(f"GIT_USER_NAME={git_user_name}")
    if git_user_email:
        lines.append(f"GIT_USER_EMAIL={git_user_email}")
    if openrouter_api_key:
        lines.append(f"OPENROUTER_API_KEY={openrouter_api_key}")

    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_path


def enable_test_paths(monkeypatch, config_path: Path) -> None:
    monkeypatch.setenv("GPMPE_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("GPMPE_USE_TEST_PATHS", "true")


def make_test_client(monkeypatch, config_path: Path) -> TestClient:
    enable_test_paths(monkeypatch, config_path)
    return TestClient(create_app())
