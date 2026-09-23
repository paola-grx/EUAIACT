"""Sample data for demo instances (EUAIACT_DEMO=1).

Creates a small fictional organisation so the dashboard, learning paths,
evidence register and records have something to show. Runs only on an
empty database. All names are fictional; demo instances must not hold real
personal data.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import evidence, inventory, refresh
from .content import get_module
from .db import get_org
from .models import Person, utcnow

ACTOR = "demo data"

PEOPLE = [
    # name, department, engagement, technical background, AI experience
    ("Alex Demo", "HR", "employee", "basic", "some"),
    ("Sam Example", "Engineering", "employee", "advanced", "extensive"),
    ("Robin Sample", "Customer Service", "employee", "none", "none"),
    ("Kim Placeholder", "Marketing", "contractor", "intermediate", "some"),
    ("Jo Fictional", "Finance", "employee", "intermediate", "some"),
]

SYSTEMS = [
    dict(name="CV Screening Assistant", vendor="(fictional vendor)", org_role="deployer", risk_class="high",
         risk_class_confirmed=True, generative=False, affected_persons=["job candidates"],
         description="Ranks incoming job applications for recruiters (Annex III, employment)."),
    dict(name="Office Copilot", vendor="(fictional vendor)", org_role="deployer", risk_class="minimal",
         risk_class_confirmed=True, generative=True, affected_persons=[],
         description="General-purpose writing and summarising assistant for all staff."),
    dict(name="Customer Chatbot", vendor="in-house", org_role="provider", risk_class="limited",
         risk_class_confirmed=False, generative=True, affected_persons=["customers"],
         description="Answers customer questions on the website (Art. 50 transparency)."),
]

ASSIGNMENTS = [
    ("Alex Demo", "CV Screening Assistant", "human_overseer"),
    ("Alex Demo", "Office Copilot", "casual_user"),
    ("Sam Example", "Customer Chatbot", "developer"),
    ("Sam Example", "Office Copilot", "casual_user"),
    ("Robin Sample", "Customer Chatbot", "operator"),
    ("Kim Placeholder", "Office Copilot", "operator"),
    ("Jo Fictional", "Office Copilot", "casual_user"),
]


def seed_demo(session: Session) -> bool:
    """Populate an empty database with sample data. Returns False if data already exists."""
    if session.scalar(select(func.count(Person.id))):
        return False
    get_org(session).org_name = "Demo Company (fictional)"
    people = {}
    for name, dept, engagement, tech, exp in PEOPLE:
        person = inventory.add_person(session, ACTOR, name=name, department=dept, engagement=engagement,
                                      email=f"{name.split()[0].lower()}@example.invalid")
        inventory.record_assessment(session, person, ACTOR, technical_background=tech, ai_experience=exp)
        people[name] = person
    systems = {s["name"]: inventory.add_system(session, ACTOR, **s) for s in SYSTEMS}
    for person, system, role in ASSIGNMENTS:
        inventory.assign(session, people[person], systems[system], role, ACTOR)

    # Some completed training, one overdue item, and non-training measures.
    today = utcnow().date()
    for name in ("Sam Example", "Jo Fictional"):
        for req in list(people[name].requirements):
            if req.completed_at is None and not req.superseded:
                version = get_module(session, req.module_key).current.version
                refresh.complete_requirement(session, req, version, ACTOR, completed_on=today - timedelta(days=5),
                                             method="classroom / live session")
    overdue = refresh.latest_requirement(people["Robin Sample"], "core")
    if overdue is not None and overdue.completed_at is None:
        overdue.due_on = today - timedelta(days=3)
    evidence.record(session, "policy_issued", "Internal AI usage policy v1.0 issued to all staff", ACTOR,
                    measure_date=today - timedelta(days=20), details={"document_version": "v1.0"})
    evidence.record(session, "awareness_session", "Lunch & learn: using AI assistants safely", ACTOR,
                    measure_date=today - timedelta(days=10),
                    details={"attendees": [p[0] for p in PEOPLE]})
    session.flush()
    return True
