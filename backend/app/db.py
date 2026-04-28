from __future__ import annotations

from pathlib import Path
import sqlite3

from .config import AppConfig


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
    existing = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name});").fetchall()
    }
    if column_name not in existing:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql};")


def initialize_database(config: AppConfig) -> None:
    config.database_path.parent.mkdir(parents=True, exist_ok=True)

    schemas_dir = Path(__file__).resolve().parents[1] / "schemas"
    migration_files = sorted(schemas_dir.glob("*.sql"))
    with sqlite3.connect(config.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON;")
        for migration in migration_files:
            connection.executescript(migration.read_text(encoding="utf-8"))
        _ensure_column(connection, "campaigns", "footnote_text", "footnote_text TEXT")
        _ensure_column(connection, "campaign_components", "footnote_text", "footnote_text TEXT")
        _ensure_column(connection, "campaign_components", "background_color", "background_color TEXT")
        _ensure_column(connection, "campaign_component_items", "background_color", "background_color TEXT")
        connection.commit()


def connect_database(config: AppConfig) -> sqlite3.Connection:
    # Keep endpoint calls robust in tests and local scripts where startup hooks may not run.
    initialize_database(config)
    connection = sqlite3.connect(config.database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection
