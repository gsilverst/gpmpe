from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .config import AppConfig
from .models import Base


def get_engine(config: AppConfig) -> Engine:
    """Create a SQLAlchemy engine based on the provided configuration."""
    # Use pool_pre_ping for RDS robustness
    engine = create_engine(config.database_url, pool_pre_ping=True)

    # Enable foreign keys for SQLite
    if config.database_url.startswith("sqlite"):
        @event.listens_for(Engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_session_factory(engine: Engine):
    """Create a configured session factory."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db(config: AppConfig):
    """FastAPI dependency for database sessions."""
    engine = get_engine(config)
    session_factory = get_session_factory(engine)
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
    existing = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name});").fetchall()
    }
    if column_name not in existing:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql};")


def _backfill_renderer_fields(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE campaign_components
        SET render_region = CASE component_kind
          WHEN 'featured-offers' THEN 'featured'
          WHEN 'weekday-specials' THEN 'secondary'
          WHEN 'other-offers' THEN 'secondary'
          WHEN 'secondary-offers' THEN 'secondary'
          WHEN 'discount-strip' THEN 'discount'
          WHEN 'legal-note' THEN 'legal'
          ELSE render_region
        END
        WHERE render_region IS NULL;
        """
    )
    connection.execute(
        """
        UPDATE campaign_components
        SET render_mode = CASE component_kind
          WHEN 'featured-offers' THEN 'offer-card-grid'
          WHEN 'weekday-specials' THEN 'strip-list'
          WHEN 'other-offers' THEN 'strip-list'
          WHEN 'secondary-offers' THEN 'strip-list'
          WHEN 'discount-strip' THEN 'discount-panel'
          WHEN 'legal-note' THEN 'legal-text'
          ELSE render_mode
        END
        WHERE render_mode IS NULL;
        """
    )


def initialize_database(config: AppConfig) -> None:
    # Ensure directory exists for SQLite
    if config.database_url.startswith("sqlite"):
        config.database_path.parent.mkdir(parents=True, exist_ok=True)

    engine = get_engine(config)
    # Create all tables defined in models.py
    Base.metadata.create_all(engine)

    # Legacy support for SQLite script migrations
    if config.database_url.startswith("sqlite"):
        schemas_dir = Path(__file__).resolve().parents[1] / "schemas"
        migration_files = sorted(schemas_dir.glob("*.sql"))
        with sqlite3.connect(config.database_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON;")
            for migration in migration_files:
                connection.executescript(migration.read_text(encoding="utf-8"))
            _ensure_column(connection, "campaigns", "footnote_text", "footnote_text TEXT")
            _ensure_column(connection, "campaign_components", "footnote_text", "footnote_text TEXT")
            _ensure_column(connection, "campaign_components", "background_color", "background_color TEXT")
            _ensure_column(connection, "campaign_components", "header_accent_color", "header_accent_color TEXT")
            _ensure_column(connection, "campaign_components", "render_region", "render_region TEXT")
            _ensure_column(connection, "campaign_components", "render_mode", "render_mode TEXT")
            _ensure_column(connection, "campaign_components", "style_json", "style_json TEXT")
            _ensure_column(connection, "campaign_component_items", "background_color", "background_color TEXT")
            _ensure_column(connection, "campaign_component_items", "render_role", "render_role TEXT")
            _ensure_column(connection, "campaign_component_items", "style_json", "style_json TEXT")
            _backfill_renderer_fields(connection)
            connection.commit()


def connect_database(config: AppConfig) -> sqlite3.Connection:
    # Keep endpoint calls robust in tests and local scripts where startup hooks may not run.
    initialize_database(config)
    connection = sqlite3.connect(config.database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection
