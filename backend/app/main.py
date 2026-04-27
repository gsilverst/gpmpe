from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import resolve_config
from .db import connect_database, initialize_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    config = resolve_config()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    initialize_database(config)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="GPMPG API", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        config = resolve_config()
        with connect_database(config) as connection:
            connection.execute("SELECT 1;")

        return {
            "status": "ok",
            "database": "ok",
            "output_dir": str(config.output_dir),
        }

    return app


app = create_app()
