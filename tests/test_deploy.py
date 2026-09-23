from pathlib import Path

import pytest
import yaml

from euaiact import cli, settings
from euaiact.settings import ROOT, normalise_database_url


@pytest.mark.parametrize("given, expected", [
    ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
    ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("sqlite:///x.db", "sqlite:///x.db"),
])
def test_database_url_normalised(given, expected):
    assert normalise_database_url(given) == expected


def test_base_url_falls_back_to_render_url(monkeypatch):
    monkeypatch.delenv("EUAIACT_BASE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://euaiact.onrender.com/")
    assert settings.load_settings().base_url == "https://euaiact.onrender.com"
    monkeypatch.setenv("EUAIACT_BASE_URL", "https://ai.example.eu")
    assert settings.load_settings().base_url == "https://ai.example.eu"
    monkeypatch.setenv("EUAIACT_BASE_URL", "")  # empty value from the platform: fall back
    assert settings.load_settings().base_url == "https://euaiact.onrender.com"


def test_render_style_production_env_is_accepted(monkeypatch):
    monkeypatch.setenv("EUAIACT_ENV", "production")
    monkeypatch.setenv("EUAIACT_SECRET_KEY", "k" * 44)
    monkeypatch.setenv("EUAIACT_DATABASE_URL", "postgresql://euaiact:pw@dpg-x-a/euaiact")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://euaiact.onrender.com")
    monkeypatch.delenv("EUAIACT_BASE_URL", raising=False)
    s = settings.load_settings()
    assert s.database_url.startswith("postgresql+psycopg://") and s.https


def test_serve_port_from_env(monkeypatch):
    captured = {}
    monkeypatch.setenv("PORT", "10000")
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: captured.update(kw))
    monkeypatch.setattr("euaiact.web.app.create_app", lambda s: object())
    assert cli.main(["serve"]) == 0
    assert captured["port"] == 10000


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_render_blueprint_is_consistent():
    bp = yaml.safe_load((ROOT / "render.yaml").read_text())
    db_names = {d["name"] for d in bp["databases"]}
    groups = {g["name"] for g in bp["envVarGroups"]}
    for svc in bp["services"]:
        assert svc["region"] == "frankfurt"
        assert Path(ROOT / svc["dockerfilePath"]).exists()
        keys = {e.get("key") for e in svc["envVars"]}
        assert {"EUAIACT_SECRET_KEY", "EUAIACT_DATABASE_URL"} <= keys
        for e in svc["envVars"]:
            if "fromDatabase" in e:
                assert e["fromDatabase"]["name"] in db_names
            if "fromGroup" in e:
                assert e["fromGroup"] in groups
    assert next(s for s in bp["services"] if s["type"] == "web")["healthCheckPath"] == "/healthz"
