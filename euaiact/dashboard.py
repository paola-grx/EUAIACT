"""Organisation-level Article 4 dashboard figures."""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import evidence
from .assessment import build_learning_path
from .db import get_org
from .models import AISystem, EvidenceEntry, Person, Requirement, utcnow
from .refresh import module_status


@dataclass
class SystemCoverage:
    system: AISystem
    people: int
    covered: int

    @property
    def percent(self) -> int:
        return round(100 * self.covered / self.people) if self.people else 0


@dataclass
class Gap:
    severity: str  # high | medium | low
    message: str
    link: str = ""


@dataclass
class Dashboard:
    people_total: int
    people_covered: int
    systems: list[SystemCoverage]
    overdue: list[Requirement]
    pending: int
    gaps: list[Gap] = field(default_factory=list)
    evidence_entries: int = 0
    chain_ok: bool = True

    @property
    def staff_percent(self) -> int:
        return round(100 * self.people_covered / self.people_total) if self.people_total else 0


def person_is_covered(session: Session, person: Person, path, module_keys: set[str] | None, today: date) -> bool:
    keys = module_keys if module_keys is not None else path.required_keys()
    return all(module_status(session, person, k, today) == "current" for k in keys)


def build_dashboard(session: Session, today: date | None = None) -> Dashboard:
    today = today or utcnow().date()
    org = get_org(session)
    people = list(session.scalars(select(Person).where(Person.active.is_(True)).order_by(Person.name)))
    systems = list(session.scalars(select(AISystem).order_by(AISystem.name)))

    paths = {p.id: build_learning_path(p, sme_mode=org.sme_mode) for p in people}
    covered_people = {p.id for p in people if person_is_covered(session, p, paths[p.id], None, today)}

    sys_cov = []
    for s in systems:
        assigned = {a.person for a in s.assignments if a.person.active}
        covered = 0
        for p in assigned:
            # Modules required because of this system, plus the general core.
            keys = {i.module_key for i in paths[p.id].items if not i.optional and s.id in i.system_ids}
            if person_is_covered(session, p, paths[p.id], keys, today):
                covered += 1
        sys_cov.append(SystemCoverage(s, len(assigned), covered))

    open_reqs = [r for p in people for r in p.requirements if r.completed_at is None and not r.superseded]
    overdue = sorted((r for r in open_reqs if r.is_overdue(today)), key=lambda r: r.due_on)

    gaps: list[Gap] = []
    for p in people:
        if p.latest_assessment is None:
            gaps.append(Gap("medium", f"{p.name}: no literacy needs assessment recorded.", f"/people/{p.id}"))
        if not p.assignments:
            gaps.append(Gap("low", f"{p.name}: not linked to any AI system.", f"/people/{p.id}"))
    for s in systems:
        if not s.assignments:
            gaps.append(Gap("medium", f"{s.name}: no staff linked to this system.", f"/systems/{s.id}"))
        if s.risk_class == "high" and not any(a.role == "human_overseer" for a in s.assignments):
            gaps.append(Gap("high", f"{s.name}: high-risk system without an assigned human overseer.", f"/systems/{s.id}"))
        if not s.risk_class_confirmed:
            gaps.append(Gap("medium", f"{s.name}: risk class not yet confirmed by a person.", f"/systems/{s.id}"))
    if overdue:
        gaps.append(Gap("high", f"{len(overdue)} overdue training item(s)."))
    if not session.scalars(select(EvidenceEntry).where(EvidenceEntry.measure_type == "policy_issued").limit(1)).first():
        gaps.append(Gap("medium", "No internal AI usage policy recorded as issued in the evidence register.", "/evidence#record"))

    chain = evidence.verify_chain(session)
    if not chain.ok:
        gaps.insert(0, Gap("high", f"Evidence register integrity check failed at entry {chain.first_broken_seq}: {chain.problem}.", "/evidence"))

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: severity_rank[g.severity])
    return Dashboard(
        people_total=len(people),
        people_covered=len(covered_people),
        systems=sys_cov,
        overdue=overdue,
        pending=len(open_reqs) - len(overdue),
        gaps=gaps,
        evidence_entries=chain.entries,
        chain_ok=chain.ok,
    )
