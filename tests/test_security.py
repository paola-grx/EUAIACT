import re
from dataclasses import replace
from datetime import timedelta

import pytest

from euaiact.settings import DEV_SECRET, ConfigError, Settings, validate


def test_post_without_csrf_token_rejected(admin):
    r = admin.post_without_csrf("/people", data={"name": "X"})
    assert r.status_code == 403
    r = admin.post_without_csrf("/people", data={"name": "X", "csrf_token": "forged"})
    assert r.status_code == 403
    assert admin.post("/people", data={"name": "X"}).status_code == 200


def test_csrf_error_is_html_for_browsers(admin):
    r = admin.post_without_csrf("/people", data={"name": "X"}, headers={"accept": "text/html"})
    assert r.status_code == 403 and "CSRF" in r.text and "<html" in r.text


def test_security_headers_and_cookie(client):
    r = client.get("/setup")
    assert "script-src 'none'" in r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert "max-age" in r.headers["strict-transport-security"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie


def test_session_rotated_on_login(admin):
    before = re.search(r'name="csrf_token" value="([^"]+)"', admin.get("/login").text).group(1)
    admin.post("/logout")
    admin.post("/login", data={"email": "ada@example.com", "password": "correct-horse-battery"})
    after = re.search(r'name="csrf_token" value="([^"]+)"', admin.get("/login").text).group(1)
    assert before != after


def test_login_throttled_after_repeated_failures(admin):
    admin.post("/logout")
    for _ in range(5):
        assert admin.post("/login", data={"email": "ada@example.com", "password": "wrong"}).status_code == 400
    r = admin.post("/login", data={"email": "ada@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 429


def test_learning_link_expiry_and_revocation(admin, settings):
    admin.post("/people", data={"name": "Lea"})
    token = re.search(r"/learn/([\w-]+)", admin.get("/people/1").text).group(1)
    assert admin.get(f"/learn/{token}").status_code == 200

    admin.post("/people/1/learn-link", data={"action": "regenerate"})
    assert admin.get(f"/learn/{token}").status_code == 404
    new_token = re.search(r"/learn/([\w-]+)", admin.get("/people/1").text).group(1)
    assert new_token != token and admin.get(f"/learn/{new_token}").status_code == 200

    # Age the link past the configured validity.
    from euaiact.models import Person

    with admin.app.state.Session() as s:
        p = s.get(Person, 1)
        p.learn_token_issued_at -= timedelta(days=181)
        s.commit()
    r = admin.get(f"/learn/{new_token}", headers={"accept": "text/html"})
    assert r.status_code == 410 and "expired" in r.text


def test_self_attested_completion_is_labelled(admin):
    admin.post("/people", data={"name": "Lea"})
    token = re.search(r"/learn/([\w-]+)", admin.get("/people/1").text).group(1)
    admin.post(f"/learn/{token}/core/complete", data={"confirm": "yes"})
    assert "self-attested via personal learning link" in admin.get("/evidence.csv").text


def base_settings(**kw) -> Settings:
    defaults = dict(database_url="postgresql+psycopg://u:p@db/euaiact", secret_key="x" * 40,
                    base_url="https://ai.example.eu", content_dir=None, legal_dates_file=None, production=True)
    return Settings(**{**defaults, **kw})


def test_production_config_accepted_when_safe():
    validate(base_settings())


@pytest.mark.parametrize("override, message", [
    ({"secret_key": DEV_SECRET}, "EUAIACT_SECRET_KEY"),
    ({"secret_key": "short"}, "EUAIACT_SECRET_KEY"),
    ({"base_url": "http://ai.example.eu"}, "https://"),
    ({"database_url": "sqlite:///x.db"}, "PostgreSQL"),
])
def test_production_config_rejects_unsafe(override, message):
    with pytest.raises(ConfigError, match=message):
        validate(base_settings(**override))


def test_development_config_is_lenient():
    validate(replace(base_settings(), production=False, secret_key=DEV_SECRET, database_url="sqlite://"))
