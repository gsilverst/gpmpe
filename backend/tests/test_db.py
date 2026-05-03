from pathlib import Path

import pytest

from app.config import AppConfig
from app.db import (
    connect_database,
    get_engine,
    get_session_factory,
    initialize_database,
    is_sqlite_database_url,
)
from app.models import Business, Campaign
from app.yaml_store import write_all_to_data_dir_session


def test_is_sqlite_database_url_detects_sqlite_variants() -> None:
    assert is_sqlite_database_url("sqlite:////tmp/gpmpe.db")
    assert is_sqlite_database_url("sqlite+pysqlite:////tmp/gpmpe.db")
    assert not is_sqlite_database_url("postgresql://user:pass@example.com:5432/gpmpe")


def test_connect_database_rejects_non_sqlite_database_url(tmp_path: Path) -> None:
    config = AppConfig(
        config_path=tmp_path / ".config",
        output_dir=tmp_path / "output",
        database_path=tmp_path / "local.db",
        database_url="postgresql://user:pass@example.com:5432/gpmpe",
        data_dir=tmp_path / "data",
        images_per_page=None,
        using_test_paths=False,
        commit_on_save=True,
        git_repo_path=None,
        git_user_name=None,
        git_user_email=None,
    )

    with pytest.raises(RuntimeError, match="SQLite/local mode"):
        connect_database(config)


def test_write_all_to_data_dir_session_exports_yaml(tmp_path: Path) -> None:
    config = AppConfig(
        config_path=tmp_path / ".config",
        output_dir=tmp_path / "output",
        database_path=tmp_path / "local.db",
        database_url=f"sqlite:///{tmp_path / 'local.db'}",
        data_dir=tmp_path / "data",
        images_per_page=None,
        using_test_paths=False,
        commit_on_save=True,
        git_repo_path=None,
        git_user_name=None,
        git_user_email=None,
    )
    initialize_database(config)
    engine = get_engine(config)
    session_factory = get_session_factory(engine)

    with session_factory() as db:
        business = Business(
            legal_name="Town Center LLC",
            display_name="town-center",
            timezone="America/New_York",
            is_active=True,
        )
        db.add(business)
        db.flush()
        db.add(
            Campaign(
                business_id=business.id,
                campaign_name="spring-sale",
                campaign_key="",
                title="Spring Sale",
                status="draft",
            )
        )
        db.commit()

    with session_factory() as db:
        write_all_to_data_dir_session(db, config.data_dir)

    assert (config.data_dir / "town-center" / "town-center.yaml").exists()
    campaign_file = config.data_dir / "town-center" / "spring-sale" / "spring-sale.yaml"
    assert campaign_file.exists()
    assert "campaign_name: spring-sale" in campaign_file.read_text(encoding="utf-8")
