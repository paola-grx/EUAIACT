"""Runtime settings, read from environment variables."""

import os
import secrets
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
    # Demo instance: sample data on an empty database and a "no real data" banner.
    demo: bool = False

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


def normalise_database_url(url: str) -> str:
    """Use the psycopg 3 driver for plain postgres:// URLs, as handed out by hosting providers."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _base_url() -> str:
    url = (
        os.environ.get("EUAIACT_BASE_URL")
        # Set by Render on web services (https://<name>.onrender.com).
        or os.environ.get("RENDER_EXTERNAL_URL")
        # Set by Hugging Face Spaces (<user>-<space>.hf.space, without scheme).
        or (f"https://{os.environ['SPACE_HOST']}" if os.environ.get("SPACE_HOST") else "")
        or "http://localhost:8000"
    )
    return url.rstrip("/")


def _secret_key(demo: bool) -> str:
    key = os.environ.get("EUAIACT_SECRET_KEY", "")
    if key:
        return key
    # A demo without a configured secret gets a random one per start: sessions end on restart,
    # which is acceptable for a demo and better than a publicly known key.
    return secrets.token_urlsafe(32) if demo else DEV_SECRET


def load_settings() -> Settings:
    demo = os.environ.get("EUAIACT_DEMO", "") == "1"
    settings = Settings(
        database_url=normalise_database_url(
            os.environ.get("EUAIACT_DATABASE_URL", f"sqlite:///{ROOT / 'var' / 'euaiact.db'}")),
        secret_key=_secret_key(demo),
        base_url=_base_url(),
        content_dir=Path(os.environ.get("EUAIACT_CONTENT_DIR", ROOT / "content")),
        legal_dates_file=Path(os.environ.get("EUAIACT_LEGAL_DATES", ROOT / "config" / "legal_dates.yaml")),
        production=os.environ.get("EUAIACT_ENV", "development") == "production",
        smtp=_smtp_from_env(),
        demo=demo,
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
