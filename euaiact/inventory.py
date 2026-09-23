"""Inventory operations that must also write evidence and fire re-training triggers."""

from datetime import timedelta

from sqlalchemy.orm import Session

from . import evidence
from .db import get_org
from .models import STAFF_ROLES, AISystem, Assessment, Assignment, Person, new_learn_token, utcnow
from .refresh import sync_requirements, trigger_assignment_change


def add_person(session: Session, actor: str, **fields) -> Person:
    person = Person(**fields)
    session.add(person)
    session.flush()
    evidence.record(session, "inventory_change", f"Person added: {person.name}", actor, person=person,
                    details={"engagement": person.engagement, "department": person.department})
    sync_requirements(session, person, actor)
    return person


def add_system(session: Session, actor: str, **fields) -> AISystem:
    system = AISystem(**fields)
    session.add(system)
    session.flush()
    evidence.record(session, "inventory_change", f"AI system added: {system.name}", actor, system_ids=[system.id],
                    details={"risk_class": system.risk_class, "org_role": system.org_role,
                             "generative": system.generative, "affected_persons": system.affected_persons})
    return system


def update_system(session: Session, system: AISystem, actor: str, **fields) -> None:
    changes = {k: v for k, v in fields.items() if getattr(system, k) != v}
    if not changes:
        return
    for k, v in changes.items():
        setattr(system, k, v)
    session.flush()
    evidence.record(session, "inventory_change", f"AI system updated: {system.name}", actor, system_ids=[system.id],
                    details={"changed": changes})
    # Risk class / generative / affected-persons changes can add modules to people's paths.
    if changes.keys() & {"risk_class", "org_role", "generative", "affected_persons"}:
        for person in {a.person for a in system.assignments}:
            sync_requirements(session, person, actor)


def assign(session: Session, person: Person, system: AISystem, role: str, actor: str) -> Assignment | None:
    if role not in STAFF_ROLES:
        raise ValueError(f"unknown role {role}")
    if any(a.system_id == system.id and a.role == role for a in person.assignments):
        return None
    new_system = not any(a.system_id == system.id for a in person.assignments)
    assignment = Assignment(person=person, system=system, role=role)
    session.add(assignment)
    session.flush()
    evidence.record(session, "inventory_change",
                    f"{person.name} linked to {system.name} as {STAFF_ROLES[role]}", actor,
                    person=person, system_ids=[system.id], details={"role": role, "new_system_for_person": new_system})
    trigger_assignment_change(session, person, system, actor, new_system=new_system)
    return assignment


def unassign(session: Session, assignment: Assignment, actor: str) -> None:
    person, system, role = assignment.person, assignment.system, assignment.role
    session.delete(assignment)
    session.flush()
    session.refresh(person)
    evidence.record(session, "inventory_change",
                    f"{person.name} no longer {STAFF_ROLES[role]} for {system.name}", actor,
                    person=person, system_ids=[system.id], details={"role": role, "removed": True})
    if any(a.system_id == system.id for a in person.assignments):
        trigger_assignment_change(session, person, system, actor, new_system=False)
    else:
        sync_requirements(session, person, actor)


def record_assessment(session: Session, person: Person, actor: str, **fields) -> Assessment:
    assessment = Assessment(person=person, created_by=actor, **fields)
    session.add(assessment)
    session.flush()
    evidence.record(session, "assessment_recorded", f"Literacy needs assessment for {person.name}", actor,
                    person=person, details={"technical_background": assessment.technical_background,
                                            "ai_experience": assessment.ai_experience})
    sync_requirements(session, person, actor)
    return assessment


def learn_link_expires(org, person: Person):
    """Expiry of the person's learning link, or None if links never expire."""
    if not org.learn_link_valid_days:
        return None
    return person.learn_token_issued_at + timedelta(days=org.learn_link_valid_days)


def learn_link_valid(org, person: Person) -> bool:
    expires = learn_link_expires(org, person)
    return person.active and (expires is None or utcnow() < expires)


def regenerate_learn_link(session: Session, person: Person, actor: str, reason: str) -> None:
    """Issue a new personal learning link; the old one stops working immediately."""
    person.learn_token = new_learn_token()
    person.learn_token_issued_at = utcnow()
    session.flush()
    evidence.record(session, "inventory_change", f"Personal learning link reissued for {person.name}", actor,
                    person=person, details={"reason": reason})


def ensure_learn_link(session: Session, person: Person, actor: str) -> None:
    if not learn_link_valid(get_org(session), person):
        regenerate_learn_link(session, person, actor, "expired")
