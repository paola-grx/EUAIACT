from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from euaiact import content
from euaiact.db import init_db, make_engine, make_sessionmaker
from euaiact.settings import ROOT, Settings
from euaiact.web.app import create_app


@pytest.fixture
def session():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    with make_sessionmaker(engine)() as s:
        content.sync_from_disk(s, ROOT / "content")
        s.commit()
        yield s


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secret_key="test",
        base_url="https://ai-literacy.example",
        content_dir=ROOT / "content",
        legal_dates_file=ROOT / "config" / "legal_dates.yaml",
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
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
