"""Versioned Markdown training content.

Seed modules live in content/modules/*.md with YAML front matter (key,
title, audience, quiz). They are imported into the database as version 1.
Every later edit, whether made in the app or re-imported from disk, creates
a new immutable ContentVersion. Edits flagged as material trigger
re-training of people who completed an earlier version (see refresh.py).
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import markdown as md
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import evidence
from .models import ContentModule, ContentVersion


@dataclass
class ModuleFile:
    key: str
    title: str
    audience: str
    body: str
    quiz: list


def parse_module(text: str) -> ModuleFile:
    if not text.startswith("---"):
        raise ValueError("module file must start with YAML front matter")
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front) or {}
    quiz = meta.get("quiz", []) or []
    validate_quiz(quiz)
    return ModuleFile(meta["key"], meta["title"], meta.get("audience", "role"), body.strip() + "\n", quiz)


def validate_quiz(quiz: list) -> None:
    for i, q in enumerate(quiz, 1):
        if not q.get("question") or not isinstance(q.get("options"), list) or len(q["options"]) < 2:
            raise ValueError(f"quiz question {i}: needs 'question' and at least two 'options'")
        if not isinstance(q.get("answer"), int) or not 0 <= q["answer"] < len(q["options"]):
            raise ValueError(f"quiz question {i}: 'answer' must be the index of the correct option")


def digest(body: str, quiz: list) -> str:
    return hashlib.sha256((body + "\n" + yaml.safe_dump(quiz, sort_keys=True)).encode("utf-8")).hexdigest()


def get_module(session: Session, key: str) -> ContentModule | None:
    return session.scalars(select(ContentModule).where(ContentModule.key == key)).first()


def all_modules(session: Session) -> list[ContentModule]:
    return list(session.scalars(select(ContentModule).order_by(ContentModule.id)))


def publish_version(
    session: Session,
    module: ContentModule,
    *,
    title: str,
    body: str,
    quiz: list,
    material_change: bool,
    change_note: str,
    actor: str,
) -> ContentVersion | None:
    """Create a new version. Returns None if nothing changed."""
    validate_quiz(quiz)
    sha = digest(body, quiz)
    if module.versions and module.current.sha256 == sha and module.current.title == title:
        return None
    version = ContentVersion(
        module=module,
        version=(module.current.version + 1) if module.versions else 1,
        title=title,
        body_markdown=body,
        quiz=quiz,
        sha256=sha,
        material_change=material_change,
        change_note=change_note,
        published_by=actor,
    )
    module.title = title
    session.add(version)
    session.flush()
    evidence.record(
        session,
        "content_version_published",
        f"Published '{title}' v{version.version}" + (" (material update)" if material_change else ""),
        actor,
        description=change_note,
        module_key=module.key,
        content_version=version.version,
        details={"sha256": sha, "material_change": material_change},
    )
    if material_change and version.version > 1:
        from .refresh import trigger_content_update

        trigger_content_update(session, module.key, version.version, actor)
    return version


def sync_from_disk(session: Session, content_dir: Path, actor: str = "system", material: bool = False,
                   only_new: bool = False) -> list[str]:
    """Import module files; new modules become v1, changed files a new version (unless only_new)."""
    changed = []
    for path in sorted((content_dir / "modules").glob("*.md")):
        mf = parse_module(path.read_text(encoding="utf-8"))
        module = get_module(session, mf.key)
        if module is None:
            module = ContentModule(key=mf.key, title=mf.title, audience=mf.audience)
            session.add(module)
            session.flush()
            publish_version(session, module, title=mf.title, body=mf.body, quiz=mf.quiz,
                            material_change=False, change_note="Initial version", actor=actor)
            changed.append(mf.key)
        elif not only_new and publish_version(session, module, title=mf.title, body=mf.body, quiz=mf.quiz,
                             material_change=material, change_note=f"Imported from {path.name}", actor=actor):
            changed.append(mf.key)
    return changed


def render(body_markdown: str) -> str:
    # Content is authored by admins; raw HTML in Markdown is escaped anyway.
    return md.markdown(_escape_html(body_markdown), extensions=["tables", "sane_lists"])


def _escape_html(text: str) -> str:
    # Leave ">" alone so Markdown blockquotes still work; "<" is enough to stop tags.
    return text.replace("<", "&lt;")


def list_templates(content_dir: Path) -> list[Path]:
    return sorted((content_dir / "templates").glob("*.md"))


def score_quiz(quiz: list, answers: dict[str, str]) -> list[dict]:
    """Feedback for each question. Used for learning reinforcement only, never as a gate."""
    results = []
    for i, q in enumerate(quiz):
        raw = answers.get(f"q{i}")
        chosen = int(raw) if raw is not None and str(raw).isdigit() else None
        results.append({
            "question": q["question"],
            "options": q["options"],
            "chosen": chosen,
            "answer": q["answer"],
            "correct": chosen == q["answer"],
            "explain": q.get("explain", ""),
        })
    return results


def required_onboarding_version(module: ContentModule) -> int:
    """Latest version app users must have completed: the last material update (or v1)."""
    material = [v.version for v in module.versions if v.material_change]
    return max(material, default=1)
