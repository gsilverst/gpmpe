from __future__ import annotations

from pathlib import Path
import sqlite3

from .config import AppConfig


def initialize_database(config: AppConfig) -> None:
    config.database_path.parent.mkdir(parents=True, exist_ok=True)

    schemas_dir = Path(__file__).resolve().parents[1] / "schemas"
    migration_files = sorted(schemas_dir.glob("*.sql"))
    with sqlite3.connect(config.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON;")
        for migration in migration_files:
            connection.executescript(migration.read_text(encoding="utf-8"))
        connection.commit()


def connect_database(config: AppConfig) -> sqlite3.Connection:
    # Keep endpoint calls robust in tests and local scripts where startup hooks may not run.
    initialize_database(config)
    connection = sqlite3.connect(config.database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection
