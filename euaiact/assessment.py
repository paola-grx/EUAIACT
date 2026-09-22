"""Contextual AI literacy needs assessment -> tailored learning path.

Art. 4 asks for measures that take into account the person's technical
knowledge, experience, education and training, the context the AI systems
are used in, and the persons they are used on. The rules below turn those
factors into a per-person path. They are a transparent heuristic, not a
legal determination: the reasons for every item are shown to the user and
admins can override by editing assignments or the assessment.
"""

from dataclasses import dataclass, field

from .models import AISystem, Assessment, Person

CORE = "core"
PRIMER = "primer"
DEVELOPER = "role-developer"
OVERSEER = "role-human-overseer"
DEPLOYER_HR = "role-deployer-high-risk"
GENAI = "role-genai-user"
AFFECTED = "affected-persons"
SME = "sme-essentials"
APP_ONBOARDING = "app-onboarding"

# Order in which modules appear in a path.
PATH_ORDER = [PRIMER, SME, CORE, DEVELOPER, OVERSEER, DEPLOYER_HR, GENAI, AFFECTED]

DEPTH_LABELS = {
    "foundation": "Foundation - plain-language walkthrough, take the examples slowly",
    "standard": "Standard - full module",
    "advanced": "Advanced - skim familiar basics, focus on obligations and edge cases",
}


@dataclass
class PathItem:
    module_key: str
    reasons: list[str] = field(default_factory=list)
    system_ids: set[int] = field(default_factory=set)
    optional: bool = False
    # True when the module exists because of specific systems (vs. general literacy).
    system_specific: bool = False


@dataclass
class LearningPath:
    depth: str
    depth_reason: str
    items: list[PathItem]
    notes: list[str] = field(default_factory=list)

    def required_keys(self) -> set[str]:
        return {i.module_key for i in self.items if not i.optional}

    def item(self, key: str) -> PathItem | None:
        return next((i for i in self.items if i.module_key == key), None)


def depth_for(assessment: Assessment | None) -> tuple[str, str]:
    if assessment is None:
        return "standard", "No needs assessment recorded yet; defaulting to the standard depth."
    tech, exp = assessment.technical_background, assessment.ai_experience
    if tech in ("none", "basic") or exp == "none":
        return "foundation", f"Technical background '{tech}' and AI experience '{exp}'."
    if tech == "advanced" and exp == "extensive":
        return "advanced", "AI/ML specialist with extensive hands-on experience."
    return "standard", f"Technical background '{tech}' and AI experience '{exp}'."


def build_learning_path(person: Person, assessment: Assessment | None = None, sme_mode: bool = False) -> LearningPath:
    assessment = assessment if assessment is not None else person.latest_assessment
    depth, depth_reason = depth_for(assessment)
    items: dict[str, PathItem] = {}

    def add(key: str, reason: str, system: AISystem | None = None, *, optional=False, specific=False) -> None:
        item = items.setdefault(key, PathItem(key, optional=optional, system_specific=specific))
        item.optional = item.optional and optional
        item.system_specific = item.system_specific or specific
        if reason not in item.reasons:
            item.reasons.append(reason)
        if system is not None:
            item.system_ids.add(system.id)

    assignments = list(person.assignments)
    all_systems = {a.system.id: a.system for a in assignments}

    if sme_mode:
        add(SME, "Minimum viable programme (SME mode): essentials for everyone who uses AI at work.")
    else:
        add(CORE, "Everyone operating AI on the organisation's behalf takes the core module.")
    for system in all_systems.values():
        items[SME if sme_mode else CORE].system_ids.add(system.id)

    if assessment is not None and depth == "foundation":
        add(PRIMER, "Foundation depth: short primer on what AI is before the main modules.", optional=sme_mode)
    if assessment is not None and assessment.technical_background == "advanced":
        items.pop(PRIMER, None)

    for a in assignments:
        s, role = a.system, a.role
        tag = f"{s.name} ({role.replace('_', ' ')})"
        if role == "developer":
            add(DEVELOPER, f"Develops or configures {tag}.", s, specific=True)
        if role == "human_overseer":
            add(OVERSEER, f"Assigned human oversight of {tag}.", s, specific=True)
        elif role == "decision_maker" and s.risk_class == "high":
            add(OVERSEER, f"Takes decisions using output of high-risk system {tag}.", s, specific=True)
        if s.risk_class == "high" and s.org_role == "deployer" and role in ("operator", "decision_maker", "human_overseer"):
            add(DEPLOYER_HR, f"Operates high-risk system {tag} as deployer (Art. 26).", s, specific=True)
        if s.generative or s.risk_class in ("limited", "gpai"):
            add(GENAI, f"Uses generative / transparency-relevant system {tag} (Art. 50).", s, specific=True)
        if (s.affected_persons and role != "casual_user") or s.risk_class == "high":
            groups = ", ".join(s.affected_persons) or "people affected by its output"
            add(AFFECTED, f"{s.name} affects {groups}.", s, specific=True,
                optional=sme_mode and s.risk_class != "high")

    notes = []
    if not assignments:
        notes.append("No AI systems linked to this person yet: only general modules are included. "
                      "Link the systems they use, develop or oversee to tailor the path.")
    if assessment is None:
        notes.append("No needs assessment recorded: the path cannot reflect this person's background yet.")
    if sme_mode:
        notes.append("SME mode: the path is the minimum viable programme. Optional items are recommended, not required.")

    ordered = [items[k] for k in PATH_ORDER if k in items]
    return LearningPath(depth, depth_reason, ordered, notes)


def modules_for_system(path: LearningPath, system_id: int) -> set[str]:
    """Required modules that exist in the path because of this system."""
    return {i.module_key for i in path.items if i.system_specific and not i.optional and system_id in i.system_ids}
