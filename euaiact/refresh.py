"""Training requirements, refresh cycle and automatic re-training triggers.

Triggers:
- initial       first time a module enters someone's learning path
- new_system    a person is linked to an AI system they were not using before
- role_change   a person's role for a system changes (added/removed role)
- content_update a module they completed received a material update
- periodic      the refresh interval (default 12 months) has elapsed
"""

import calendar
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import evidence
from .assessment import CORE, SME, build_learning_path, modules_for_system
from .db import get_org
from .models import Person, Reminder, Requirement, utcnow

INITIAL_DUE_DAYS = 30


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _today() -> date:
    return utcnow().date()


def latest_requirement(person: Person, module_key: str) -> Requirement | None:
    reqs = [r for r in person.requirements if r.module_key == module_key and not r.superseded]
    return max(reqs, key=lambda r: (r.assigned_at, r.id or 0)) if reqs else None


def completion_expires(session: Session, req: Requirement) -> date | None:
    if req.completed_at is None:
        return None
    return add_months(req.completed_at.date(), get_org(session).refresh_interval_months)


def module_status(session: Session, person: Person, module_key: str, today: date | None = None) -> str:
    """One of: not_assigned, pending, overdue, current, expired."""
    today = today or _today()
    req = latest_requirement(person, module_key)
    if req is None:
        return "not_assigned"
    if req.completed_at is None:
        return "overdue" if req.is_overdue(today) else "pending"
    return "current" if today < completion_expires(session, req) else "expired"


def _new_requirement(session, person, item, trigger, reason, actor, due_on) -> Requirement:
    req = Requirement(
        person=person,
        module_key=item.module_key,
        system_ids=sorted(item.system_ids),
        reason=reason,
        trigger=trigger,
        due_on=due_on,
    )
    session.add(req)
    session.flush()
    measure = "training_assigned" if trigger == "initial" else "retraining_triggered"
    evidence.record(
        session, measure, f"{item.module_key} assigned to {person.name} ({trigger.replace('_', ' ')})", actor,
        description=reason, person=person, system_ids=sorted(item.system_ids), module_key=item.module_key,
        details={"trigger": trigger, "due_on": due_on.isoformat(), "requirement_id": req.id},
    )
    return req


def sync_requirements(
    session: Session,
    person: Person,
    actor: str,
    *,
    trigger: str = "initial",
    reason: str = "",
    force_modules: set[str] | None = None,
) -> list[Requirement]:
    """Bring a person's requirements in line with their current learning path.

    Modules in the path without a requirement get one. Modules listed in
    force_modules get a fresh requirement even if already completed (a
    re-training). Open requirements for modules no longer in the path are
    marked superseded.
    """
    org = get_org(session)
    session.flush()
    session.refresh(person)
    path = build_learning_path(person, sme_mode=org.sme_mode)
    required = path.required_keys()
    force_modules = (force_modules or set()) & required
    today = _today()
    created = []
    for item in path.items:
        if item.optional:
            continue
        latest = latest_requirement(person, item.module_key)
        why = " ".join(item.reasons)
        if latest is None:
            created.append(_new_requirement(session, person, item, "initial", why, actor,
                                            today + timedelta(days=INITIAL_DUE_DAYS)))
        elif item.module_key in force_modules and latest.completed_at is not None:
            created.append(_new_requirement(session, person, item, trigger, f"{reason} {why}".strip(), actor,
                                            today + timedelta(days=INITIAL_DUE_DAYS)))
        else:
            latest.system_ids = sorted(item.system_ids)
    for req in person.requirements:
        if req.completed_at is None and not req.superseded and req.module_key not in required:
            req.superseded = True
    session.flush()
    return created


def trigger_assignment_change(session: Session, person: Person, system, actor: str, *, new_system: bool) -> list[Requirement]:
    """Call after a person gains/changes a role on a system."""
    org = get_org(session)
    session.flush()
    session.refresh(person)
    path = build_learning_path(person, sme_mode=org.sme_mode)
    force = modules_for_system(path, system.id)
    if not force:
        # The system adds no role-specific module (e.g. a general chatbot):
        # re-visit the core module, which covers the internal AI usage policy.
        force = {SME if org.sme_mode else CORE}
    trigger = "new_system" if new_system else "role_change"
    reason = (f"New AI system in use: {system.name}." if new_system
              else f"Role change for {system.name}.")
    return sync_requirements(session, person, actor, trigger=trigger, reason=reason, force_modules=force)


def trigger_content_update(session: Session, module_key: str, version: int, actor: str) -> list[Requirement]:
    """A module received a material update: re-train people who completed an earlier version."""
    org = get_org(session)
    created = []
    for person in session.scalars(select(Person).where(Person.active.is_(True))):
        latest = latest_requirement(person, module_key)
        if latest is None or latest.completed_at is None or (latest.completed_version or 0) >= version:
            continue
        item = build_learning_path(person, sme_mode=org.sme_mode).item(module_key)
        if item is None or item.optional:
            continue
        created.append(_new_requirement(
            session, person, item, "content_update",
            f"Module materially updated to v{version}; previously completed v{latest.completed_version}.",
            actor, _today() + timedelta(days=INITIAL_DUE_DAYS),
        ))
    return created


def complete_requirement(session: Session, req: Requirement, version: int, actor: str, *,
                         completed_on: date | None = None, method: str = "self-paced in app", note: str = "") -> None:
    if req.completed_at is not None:
        return
    now = utcnow()
    req.completed_at = datetime.combine(completed_on, now.time()) if completed_on else now
    req.completed_version = version
    session.flush()
    evidence.record(
        session, "training_completed", f"{req.module_key} v{version} completed by {req.person.name}", actor,
        description=note, person=req.person, system_ids=req.system_ids, module_key=req.module_key,
        content_version=version, measure_date=req.completed_at.date(),
        details={"requirement_id": req.id, "trigger": req.trigger, "due_on": req.due_on.isoformat(),
                 "on_time": req.completed_at.date() <= req.due_on, "method": method},
    )


def run_refresh_cycle(session: Session, actor: str = "system", today: date | None = None) -> dict:
    """Periodic job: create refresh requirements and queue reminders.

    Safe to run repeatedly (e.g. daily from cron); it does not duplicate work.
    """
    today = today or _today()
    org = get_org(session)
    lead = timedelta(days=org.reminder_lead_days)
    stats = {"periodic_created": 0, "reminders_queued": 0}
    for person in session.scalars(select(Person).where(Person.active.is_(True))):
        path = build_learning_path(person, sme_mode=org.sme_mode)
        for item in path.items:
            if item.optional:
                continue
            latest = latest_requirement(person, item.module_key)
            if latest is None or latest.completed_at is None:
                continue
            expires = completion_expires(session, latest)
            if today + lead >= expires:
                _new_requirement(
                    session, person, item, "periodic",
                    f"Refresh cycle: {org.refresh_interval_months} months since completion on "
                    f"{latest.completed_at.date().isoformat()}.",
                    actor, expires,
                )
                stats["periodic_created"] += 1
        for req in person.requirements:
            if req.completed_at is not None or req.superseded:
                continue
            kind = "overdue" if req.is_overdue(today) else ("due_soon" if req.due_on - today <= lead else None)
            if kind is None:
                continue
            exists = session.scalars(select(Reminder).where(
                Reminder.requirement_id == req.id, Reminder.kind == kind)).first()
            if exists:
                continue
            session.add(Reminder(person_id=person.id, requirement_id=req.id, kind=kind))
            evidence.record(
                session, "reminder_issued", f"{kind.replace('_', ' ')} reminder: {req.module_key} for {person.name}",
                actor, person=person, module_key=req.module_key,
                details={"requirement_id": req.id, "due_on": req.due_on.isoformat(), "kind": kind},
            )
            stats["reminders_queued"] += 1
    session.flush()
    return stats
