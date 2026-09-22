"""FastAPI application: server-rendered UI for the Article 4 AI literacy module."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .. import content
from ..assessment import APP_ONBOARDING, DEPTH_LABELS
from ..db import init_db, make_engine, make_sessionmaker
from ..legal_dates import load_milestones, unverified
from ..models import (
    APP_USER_ROLES,
    EXPERIENCE_LEVELS,
    MEASURE_TYPES,
    ORG_ROLES,
    RISK_CLASSES,
    STAFF_ROLES,
    TECH_LEVELS,
)
from ..settings import Settings, load_settings

HERE = Path(__file__).parent

# Paths reachable without login / without finished onboarding.
PUBLIC_PREFIXES = ("/static", "/verify", "/learn", "/login", "/setup")
ONBOARDING_EXEMPT = PUBLIC_PREFIXES + ("/onboarding", "/guidance", "/logout", "/legal-dates")


class NeedsLogin(Exception):
    pass


class NeedsOnboarding(Exception):
    pass


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = make_engine(settings.database_url)
    Session = make_sessionmaker(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine)
        with Session() as s:
            content.sync_from_disk(s, settings.content_dir, only_new=True)
            s.commit()
        yield

    app = FastAPI(title="EU AI Act - Article 4 AI Literacy", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.Session = Session
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    templates = Jinja2Templates(directory=HERE / "templates")
    milestones = load_milestones(settings.legal_dates_file)
    templates.env.globals.update(
        STAFF_ROLES=STAFF_ROLES, RISK_CLASSES=RISK_CLASSES, ORG_ROLES=ORG_ROLES, TECH_LEVELS=TECH_LEVELS,
        EXPERIENCE_LEVELS=EXPERIENCE_LEVELS, MEASURE_TYPES=MEASURE_TYPES, APP_USER_ROLES=APP_USER_ROLES,
        DEPTH_LABELS=DEPTH_LABELS, APP_ONBOARDING=APP_ONBOARDING,
        LEGAL_DATES_UNVERIFIED=len(unverified(milestones)),
    )
    templates.env.filters["md"] = content.render
    app.state.templates = templates
    app.state.milestones = milestones

    @app.exception_handler(NeedsLogin)
    async def _login(request: Request, _exc):
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(NeedsOnboarding)
    async def _onboard(request: Request, _exc):
        return RedirectResponse("/onboarding", status_code=303)

    from . import routes

    app.include_router(routes.router)
    return app
