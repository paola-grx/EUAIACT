import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from euaiact import content
from euaiact.db import init_db, make_engine, make_sessionmaker
from euaiact.settings import ROOT, Settings
from euaiact.web.app import create_app


# Set to run the suite against PostgreSQL, e.g.
# EUAIACT_TEST_DATABASE_URL=postgresql+psycopg://euaiact:euaiact@localhost/euaiact_test
PG_URL = os.environ.get("EUAIACT_TEST_DATABASE_URL", "")


def fresh_database_url(tmp_path: Path) -> str:
    if not PG_URL:
        return f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    return PG_URL


@pytest.fixture
def session(tmp_path):
    engine = make_engine(fresh_database_url(tmp_path) if PG_URL else "sqlite:///:memory:")
    init_db(engine)
    with make_sessionmaker(engine)() as s:
        content.sync_from_disk(s, ROOT / "content")
        s.commit()
        yield s


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=fresh_database_url(tmp_path),
        secret_key="test",
        base_url="https://ai-literacy.example",
        content_dir=ROOT / "content",
        legal_dates_file=ROOT / "config" / "legal_dates.yaml",
    )


CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


class CsrfClient(TestClient):
    """Test client that adds the session's CSRF token to form posts, like a browser would."""

    def request(self, method, url, *args, csrf=True, **kwargs):
        if csrf and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            page = super().request("GET", "/login", follow_redirects=True)
            token = CSRF_RE.search(page.text).group(1)
            kwargs["data"] = {**(kwargs.get("data") or {}), "csrf_token": token}
        return super().request(method, url, *args, **kwargs)

    def post_without_csrf(self, url, **kwargs):
        return self.request("POST", url, csrf=False, **kwargs)


@pytest.fixture
def client(settings):
    with CsrfClient(create_app(settings), base_url="https://testserver") as c:
        yield c


@pytest.fixture
def admin(client):
    """A logged-in admin who has completed the app onboarding."""
    r = client.post("/setup", data={"org_name": "Acme GmbH", "name": "Ada Admin", "email": "ada@example.com",
                                    "password": "correct-horse-battery"}, follow_redirects=False)
    assert r.status_code == 303
    r = client.post("/onboarding/complete", data={"confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303
    return client
