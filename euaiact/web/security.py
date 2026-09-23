"""CSRF protection, security headers and login throttling."""

import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from markupsafe import Markup

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "script-src 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # Learning links carry a secret in the URL: never leak it via Referer.
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def csrf_input(request: Request) -> Markup:
    return Markup(f'<input type="hidden" name="{CSRF_FIELD}" value="{csrf_token(request)}">')


async def csrf_protect(request: Request) -> None:
    """Router dependency: reject state-changing requests without the session's CSRF token."""
    if request.method not in UNSAFE_METHODS:
        return
    expected = request.session.get("csrf")
    supplied = request.headers.get(CSRF_HEADER)
    if supplied is None:
        form = await request.form()
        supplied = form.get(CSRF_FIELD)
    if not expected or not isinstance(supplied, str) or not hmac.compare_digest(expected, supplied):
        raise HTTPException(403, "Invalid or missing CSRF token. Reload the page and try again.")


def add_security_headers(response, path: str, https: bool) -> None:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if not path.startswith("/static"):
        # Pages contain personal data and personal links: do not cache.
        response.headers.setdefault("Cache-Control", "no-store")
    if https:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


class LoginThrottle:
    """Blocks an e-mail/IP pair after too many failed logins in a time window.

    In-memory, so per process: with several workers the effective limit is
    multiplied by the worker count. Put a reverse-proxy rate limit in front
    for stronger guarantees.
    """

    def __init__(self, max_failures: int = 5, window_seconds: int = 900):
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[tuple[str, str], deque] = defaultdict(deque)

    def _recent(self, key: tuple[str, str]) -> deque:
        q = self._failures[key]
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, email: str, ip: str) -> bool:
        return len(self._recent((email, ip))) >= self.max_failures

    def fail(self, email: str, ip: str) -> None:
        self._recent((email, ip)).append(time.monotonic())

    def reset(self, email: str, ip: str) -> None:
        self._failures.pop((email, ip), None)
