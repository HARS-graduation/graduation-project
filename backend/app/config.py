"""Runtime configuration, read from environment variables.

Every value has a local-development default so the service runs with zero setup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    ingest_api_key: str | None = None
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://localhost:3000",
    )
    seed_demo_cameras: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        db_path = Path(os.getenv("ALERTS_DB_PATH", "data/alerts.db"))
        api_key = os.getenv("INGEST_API_KEY", "").strip() or None
        origins = tuple(
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
            ).split(",")
            if origin.strip()
        )
        seed = os.getenv("SEED_DEMO_CAMERAS", "1").lower() not in {"0", "false", "no"}
        return cls(
            db_path=db_path,
            ingest_api_key=api_key,
            cors_origins=origins,
            seed_demo_cameras=seed,
        )
