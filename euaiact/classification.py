"""Suggested risk class for an AI system, from a short questionnaire.

This is a screening aid only. The in-app guidance page
(/guidance/automation-limits) explains its limits, and a suggested class
stays "unconfirmed" until a person confirms it on the system page.
"""

from dataclasses import dataclass, field

# Annex III areas, abbreviated for the questionnaire.
ANNEX_III_AREAS = {
    "biometrics": "Biometric identification, categorisation or emotion recognition",
    "critical_infrastructure": "Safety component of critical infrastructure",
    "education": "Education and vocational training (admission, assessment, proctoring)",
    "employment": "Employment and workers management (recruitment, promotion, task allocation, monitoring)",
    "essential_services": "Access to essential private/public services (credit scoring, benefits, insurance pricing, emergency triage)",
    "law_enforcement": "Law enforcement",
    "migration": "Migration, asylum and border control",
    "justice": "Administration of justice and democratic processes",
}

LIMITS = [
    "It only covers the questions asked; it cannot see how the system is actually configured or used.",
    "It does not assess the Art. 6(3) exceptions (narrow procedural tasks, preparatory tasks, etc.); "
    "a system in an Annex III area may not be high-risk if an exception applies, and that needs a documented assessment.",
    "It does not check for prohibited practices under Art. 5; those need separate legal review.",
    "Annex I (product safety legislation) is detected only by a single yes/no question.",
    "Legal dates and obligations change (e.g. Regulation (EU) 2026/1744); the underlying rules are "
    "updated by the app maintainers and may lag behind the law.",
    "The result is a suggestion for a human to confirm, not legal advice.",
]


@dataclass
class Suggestion:
    risk_class: str
    generative: bool
    rationale: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def suggest(
    *,
    annex_iii_areas: list[str],
    annex_i_product: bool,
    interacts_with_people: bool,
    generates_content: bool,
    general_purpose: bool,
) -> Suggestion:
    rationale, caveats = [], []
    if annex_i_product:
        risk = "high"
        rationale.append("Safety component of, or itself, a product under Annex I legislation.")
    elif annex_iii_areas:
        risk = "high"
        areas = ", ".join(ANNEX_III_AREAS.get(a, a) for a in annex_iii_areas)
        rationale.append(f"Used in Annex III area(s): {areas}.")
        caveats.append("Check whether an Art. 6(3) exception applies and document that assessment.")
    elif generates_content or interacts_with_people:
        risk = "limited"
        if interacts_with_people:
            rationale.append("Interacts directly with natural persons (Art. 50(1)).")
        if generates_content:
            rationale.append("Generates synthetic text, audio, image or video (Art. 50(2)/(4)).")
    elif general_purpose:
        risk = "gpai"
        rationale.append("General-purpose model or system.")
    else:
        risk = "minimal"
        rationale.append("No high-risk area, transparency trigger or GPAI use identified.")
    if general_purpose and risk != "gpai":
        caveats.append("Also a general-purpose AI system: GPAI provider obligations may apply upstream.")
    caveats.append("Art. 4 AI literacy measures apply regardless of the risk class.")
    return Suggestion(risk, generates_content, rationale, caveats)
