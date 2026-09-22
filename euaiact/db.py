"""Engine/session setup and schema initialisation."""

from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, OrgSettings

# Database-level guarantees that evidence and issued documents are append-only.
_IMMUTABLE_TABLES = ("evidence", "issued_documents", "content_versions")


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///") and not database_url.startswith("sqlite:///:memory:"):
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url, connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {})
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            for table in _IMMUTABLE_TABLES:
                for op in ("UPDATE", "DELETE"):
                    conn.execute(text(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op.lower()} "
                        f"BEFORE {op} ON {table} "
                        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
                    ))
    with Session(engine) as session:
        if session.get(OrgSettings, 1) is None:
            session.add(OrgSettings(id=1))
            session.commit()


def make_sessionmaker(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_org(session: Session) -> OrgSettings:
    return session.get(OrgSettings, 1)
