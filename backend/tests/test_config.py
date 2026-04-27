from pathlib import Path

from app.config import load_key_value_file, resolve_config


def test_load_key_value_file_parses_key_value_lines(tmp_path: Path) -> None:
    config_path = tmp_path / ".config"
    config_path.write_text(
        "# Comment\nOUTPUT_DIR=./out\nDATABASE_PATH=./db/local.db\nINVALID_LINE\n", encoding="utf-8"
    )

    values = load_key_value_file(config_path)

    assert values["OUTPUT_DIR"] == "./out"
    assert values["DATABASE_PATH"] == "./db/local.db"
    assert "INVALID_LINE" not in values


def test_resolve_config_falls_back_to_cwd_when_config_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)

    config = resolve_config(repo_root=repo_root, cwd=tmp_path)

    assert config.output_dir == tmp_path.resolve()
    assert config.database_path == (repo_root / "backend" / "data" / "gpmpg.db").resolve()
