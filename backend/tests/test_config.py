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
    assert config.database_path == (repo_root / "backend" / "data" / "gpmpg.db").resolve()
    assert config.data_dir == (repo_root / "tests" / "data").resolve()
    assert config.yaml_auto_commit is False


def test_resolve_config_reads_yaml_auto_commit_flag(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    config_path = repo_root / ".config"
    config_path.write_text("DATA_DIR=./tests/data\nYAML_AUTO_COMMIT=true\n", encoding="utf-8")

    config = resolve_config(repo_root=repo_root, cwd=tmp_path)

    assert config.yaml_auto_commit is True
