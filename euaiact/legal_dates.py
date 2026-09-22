"""Loader and release check for the legal dates config (config/legal_dates.yaml)."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Milestone:
    key: str
    label: str
    applies_from: date
    articles: list[str] = field(default_factory=list)
    notes: str = ""
    verified: bool = False
    verified_by: str = ""
    verified_on: date | None = None
    source: str = ""

    def status(self, today: date) -> str:
        return "applies" if today >= self.applies_from else "upcoming"


def load_milestones(path: Path) -> list[Milestone]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    milestones = []
    for raw in data["milestones"]:
        applies_from = raw["applies_from"]
        if isinstance(applies_from, str):
            applies_from = date.fromisoformat(applies_from)
        milestones.append(
            Milestone(
                key=raw["key"],
                label=raw["label"],
                applies_from=applies_from,
                articles=list(raw.get("articles", [])),
                notes=raw.get("notes", ""),
                verified=bool(raw.get("verified", False)),
                verified_by=raw.get("verified_by", ""),
                verified_on=raw.get("verified_on"),
                source=raw.get("source", ""),
            )
        )
    return sorted(milestones, key=lambda m: m.applies_from)


def unverified(milestones: list[Milestone]) -> list[Milestone]:
    return [m for m in milestones if not (m.verified and m.verified_by and m.verified_on)]
