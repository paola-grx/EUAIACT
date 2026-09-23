"""Runtime settings, read from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEV_SECRET = "dev-only-change-me"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    sender: str = ""
    # "starttls" (port 587), "ssl" (port 465) or "none" (local relay only).
    security: str = "starttls"


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    base_url: str
    content_dir: Path
    legal_dates_file: Path
    production: bool = False
    smtp: SmtpSettings | None = None

    @property
    def https(self) -> bool:
        return self.base_url.startswith("https://")


def _smtp_from_env() -> SmtpSettings | None:
    host = os.environ.get("EUAIACT_SMTP_HOST", "")
    if not host:
        return None
    security = os.environ.get("EUAIACT_SMTP_SECURITY", "starttls")
    default_port = {"ssl": 465, "none": 25}.get(security, 587)
    return SmtpSettings(
        host=host,
        port=int(os.environ.get("EUAIACT_SMTP_PORT", default_port)),
        username=os.environ.get("EUAIACT_SMTP_USERNAME", ""),
        password=os.environ.get("EUAIACT_SMTP_PASSWORD", ""),
        sender=os.environ.get("EUAIACT_SMTP_FROM", ""),
        security=security,
    )


def load_settings() -> Settings:
    settings = Settings(
        database_url=os.environ.get("EUAIACT_DATABASE_URL", f"sqlite:///{ROOT / 'var' / 'euaiact.db'}"),
        secret_key=os.environ.get("EUAIACT_SECRET_KEY", DEV_SECRET),
        base_url=os.environ.get("EUAIACT_BASE_URL", "http://localhost:8000").rstrip("/"),
        content_dir=Path(os.environ.get("EUAIACT_CONTENT_DIR", ROOT / "content")),
        legal_dates_file=Path(os.environ.get("EUAIACT_LEGAL_DATES", ROOT / "config" / "legal_dates.yaml")),
        production=os.environ.get("EUAIACT_ENV", "development") == "production",
        smtp=_smtp_from_env(),
    )
    validate(settings)
    return settings


def validate(settings: Settings) -> None:
    """Refuse unsafe configuration in production (EUAIACT_ENV=production)."""
    if settings.smtp is not None:
        if settings.smtp.security not in ("starttls", "ssl", "none"):
            raise ConfigError("EUAIACT_SMTP_SECURITY must be starttls, ssl or none")
        if not settings.smtp.sender:
            raise ConfigError("EUAIACT_SMTP_FROM is required when EUAIACT_SMTP_HOST is set")
    if not settings.production:
        return
    problems = []
    if settings.secret_key == DEV_SECRET or len(settings.secret_key) < 32:
        problems.append("EUAIACT_SECRET_KEY must be set to a random value of at least 32 characters")
    if not settings.https:
        problems.append("EUAIACT_BASE_URL must be an https:// URL (used for cookies, QR codes and learning links)")
    if settings.database_url.startswith("sqlite"):
        problems.append("use PostgreSQL in production (EUAIACT_DATABASE_URL=postgresql+psycopg://...)")
    if settings.smtp is not None and settings.smtp.security == "none":
        problems.append("EUAIACT_SMTP_SECURITY=none is not allowed in production")
    if problems:
        raise ConfigError("Unsafe production configuration:\n- " + "\n- ".join(problems))
