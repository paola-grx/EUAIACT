"""Runtime settings, read from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    base_url: str
    content_dir: Path
    legal_dates_file: Path


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("EUAIACT_DATABASE_URL", f"sqlite:///{ROOT / 'var' / 'euaiact.db'}"),
        secret_key=os.environ.get("EUAIACT_SECRET_KEY", "dev-only-change-me"),
        base_url=os.environ.get("EUAIACT_BASE_URL", "http://localhost:8000").rstrip("/"),
        content_dir=Path(os.environ.get("EUAIACT_CONTENT_DIR", ROOT / "content")),
        legal_dates_file=Path(os.environ.get("EUAIACT_LEGAL_DATES", ROOT / "config" / "legal_dates.yaml")),
    )
