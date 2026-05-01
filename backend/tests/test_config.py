from pathlib import Path

from app.config import load_key_value_file, resolve_config


def test_load_key_value_file_parses_key_value_lines(tmp_path: Path) -> None:
    config_path = tmp_path / ".config"
    config_path.write_text(
        "# Comment\nOUTPUT_DIR=./out\nDATABASE_PATH=./db/local.db\nDATA_DIR=./data\nINVALID_LINE\n", encoding="utf-8"
    )

    values = load_key_value_file(config_path)

    assert values["OUTPUT_DIR"] == "./out"
    assert values["DATABASE_PATH"] == "./db/local.db"
    assert values["DATA_DIR"] == "./data"
    assert "INVALID_LINE" not in values


def test_resolve_config_requires_data_dir(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    try:
        resolve_config(repo_root=repo_root, cwd=tmp_path)
    except ValueError as error:
        assert str(error) == "DATA_DIR must be configured in .config"
    else:
        raise AssertionError("Expected DATA_DIR configuration error")

def test_resolve_config_loads_configured_data_dir(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text("DATA_DIR=./tests/data\n", encoding="utf-8")

    config = resolve_config(repo_root=repo_root, cwd=tmp_path)

    assert config.output_dir == tmp_path.resolve()
    assert config.database_path == (repo_root / "backend" / "data" / "gpmpe.db").resolve()
    assert config.data_dir == (repo_root / "tests" / "data").resolve()
    assert config.images_per_page is None
    assert config.using_test_paths is False
    assert config.commit_on_save is True
    assert config.git_repo_path is None
    assert config.git_user_name is None
    assert config.git_user_email is None


def test_resolve_config_environment_overrides_storage_paths(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text(
        "OUTPUT_DIR=./configured-output\n"
        "DATABASE_PATH=./configured.db\n"
        "DATA_DIR=./configured-data\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OUTPUT_DIR", "/mnt/efs/output")
    monkeypatch.setenv("DATABASE_PATH", "/mnt/efs/db/gpmpe.db")
    monkeypatch.setenv("DATA_DIR", "/mnt/efs/data")

    config = resolve_config(repo_root=repo_root, cwd=tmp_path)

    assert config.output_dir == Path("/mnt/efs/output")
    assert config.database_path == Path("/mnt/efs/db/gpmpe.db")
    assert config.data_dir == Path("/mnt/efs/data")
    assert config.database_url == "sqlite:////mnt/efs/db/gpmpe.db"


def test_resolve_config_environment_database_url_overrides_sqlite_path(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text(
        "DATABASE_URL=sqlite:///configured.db\n"
        "DATABASE_PATH=./configured.db\n"
        "DATA_DIR=./configured-data\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@example.com:5432/gpmpe")

    config = resolve_config(repo_root=repo_root, cwd=tmp_path)

    assert config.database_url == "postgresql://user:pass@example.com:5432/gpmpe"


def test_resolve_config_reads_commit_on_save_and_git_settings(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text(
        "DATA_DIR=./tests/data\n"
        "COMMIT_ON_SAVE=false\n"
        "GIT_REPO_PATH=.\n"
        "GIT_USER_NAME=Test User\n"
        "GIT_USER_EMAIL=test@example.com\n",
        encoding="utf-8",
    )

    config = resolve_config(repo_root=repo_root, cwd=tmp_path)

    assert config.commit_on_save is False
    assert config.git_repo_path == repo_root.resolve()
    assert config.git_user_name == "Test User"
    assert config.git_user_email == "test@example.com"
    assert config.git_push_enabled is False
    assert config.git_remote == "origin"
    assert config.git_branch == "HEAD"
    assert config.git_lock_timeout_seconds == 30.0


def test_resolve_config_reads_git_sync_settings(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text(
        "DATA_DIR=./tests/data\n"
        "GIT_PUSH_ENABLED=true\n"
        "GIT_REMOTE=upstream\n"
        "GIT_BRANCH=main\n",
        encoding="utf-8",
    )

    config = resolve_config(repo_root=repo_root, cwd=tmp_path)

    assert config.git_push_enabled is True
    assert config.git_remote == "upstream"
    assert config.git_branch == "main"


def test_resolve_config_reads_git_lock_timeout(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text(
        "DATA_DIR=./tests/data\n"
        "GIT_LOCK_TIMEOUT_SECONDS=2.5\n",
        encoding="utf-8",
    )

    config = resolve_config(repo_root=repo_root, cwd=tmp_path)

    assert config.git_lock_timeout_seconds == 2.5


def test_resolve_config_reads_images_per_page(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text(
        "DATA_DIR=./tests/data\n"
        "IMAGES_PER_PAGE=4\n",
        encoding="utf-8",
    )

    config = resolve_config(repo_root=repo_root, cwd=tmp_path)
    assert config.images_per_page == 4


def test_resolve_config_rejects_invalid_images_per_page(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text(
        "DATA_DIR=./tests/data\n"
        "IMAGES_PER_PAGE=one\n",
        encoding="utf-8",
    )

    try:
        resolve_config(repo_root=repo_root, cwd=tmp_path)
    except ValueError as error:
        assert str(error) == "IMAGES_PER_PAGE must be an integer"
    else:
        raise AssertionError("Expected IMAGES_PER_PAGE integer validation error")


def test_resolve_config_rejects_images_per_page_less_than_two(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text(
        "DATA_DIR=./tests/data\n"
        "IMAGES_PER_PAGE=1\n",
        encoding="utf-8",
    )

    try:
        resolve_config(repo_root=repo_root, cwd=tmp_path)
    except ValueError as error:
        assert str(error) == "IMAGES_PER_PAGE must be >= 2"
    else:
        raise AssertionError("Expected IMAGES_PER_PAGE minimum validation error")


def test_resolve_config_uses_test_paths_when_enabled(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text(
        "DATA_DIR=./runtime-data\n"
        "DATABASE_PATH=./runtime.db\n"
        "TEST_DATA_DIR=./test-data\n"
        "TEST_DATABASE_PATH=./test.db\n",
        encoding="utf-8",
    )

    config = resolve_config(repo_root=repo_root, cwd=tmp_path, use_test_paths=True)

    assert config.database_path == (repo_root / "test.db").resolve()
    assert config.data_dir == (repo_root / "test-data").resolve()
    assert config.using_test_paths is True


def test_resolve_config_ignores_test_paths_when_not_enabled(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text(
        "DATA_DIR=./runtime-data\n"
        "DATABASE_PATH=./runtime.db\n"
        "TEST_DATA_DIR=./test-data\n"
        "TEST_DATABASE_PATH=./test.db\n",
        encoding="utf-8",
    )

    config = resolve_config(repo_root=repo_root, cwd=tmp_path, use_test_paths=False)

    assert config.database_path == (repo_root / "runtime.db").resolve()
    assert config.data_dir == (repo_root / "runtime-data").resolve()
    assert config.using_test_paths is False


def test_resolve_config_requires_both_test_paths_when_enabled(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text(
        "DATA_DIR=./runtime-data\n"
        "TEST_DATABASE_PATH=./test.db\n",
        encoding="utf-8",
    )

    try:
        resolve_config(repo_root=repo_root, cwd=tmp_path, use_test_paths=True)
    except ValueError as error:
        assert str(error) == "TEST_DATABASE_PATH and TEST_DATA_DIR must both be configured when test paths are enabled"
    else:
        raise AssertionError("Expected paired test path validation error")
