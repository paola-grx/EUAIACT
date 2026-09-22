"""Database models for the Article 4 AI literacy module."""

import secrets
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Current UTC time, naive (SQLite does not keep tzinfo), second precision."""
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)


class Base(DeclarativeBase):
    pass


# Controlled vocabularies ---------------------------------------------------

STAFF_ROLES = {
    "developer": "Developer",
    "operator": "Operator",
    "decision_maker": "Decision-maker",
    "human_overseer": "Human overseer",
    "casual_user": "Casual user",
}

RISK_CLASSES = {
    "high": "High-risk (Art. 6 / Annex I or III)",
    "limited": "Transparency obligations (Art. 50)",
    "gpai": "General-purpose AI model / system",
    "minimal": "Minimal risk (incl. general chatbots/copilots)",
}

ORG_ROLES = {"provider": "Provider", "deployer": "Deployer"}

TECH_LEVELS = {
    "none": "No technical background",
    "basic": "Basic digital skills",
    "intermediate": "Technical / data-literate",
    "advanced": "AI / ML specialist",
}

EXPERIENCE_LEVELS = {
    "none": "Has not used AI tools at work",
    "some": "Occasional use of AI tools",
    "extensive": "Regular, in-depth use of AI tools",
}

APP_USER_ROLES = {"admin": "Administrator", "reviewer": "Reviewer"}

MEASURE_TYPES = {
    "training_assigned": "Training assigned",
    "training_completed": "Training completed",
    "knowledge_check_taken": "Knowledge check taken (reinforcement only)",
    "retraining_triggered": "Re-training triggered",
    "reminder_issued": "Refresh reminder issued",
    "content_version_published": "Training content version published",
    "policy_issued": "Internal AI policy issued",
    "awareness_session": "Awareness session held",
    "guidance_doc": "Guidance document issued",
    "inventory_change": "AI system / role inventory change",
    "assessment_recorded": "Literacy needs assessment recorded",
    "document_issued": "Record / statement issued",
    "settings_changed": "Programme settings changed",
    "other_measure": "Other measure",
}


# Organisation --------------------------------------------------------------

class OrgSettings(Base):
    __tablename__ = "org_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_name: Mapped[str] = mapped_column(String(200), default="Our organisation")
    refresh_interval_months: Mapped[int] = mapped_column(Integer, default=12)
    reminder_lead_days: Mapped[int] = mapped_column(Integer, default=30)
    sme_mode: Mapped[bool] = mapped_column(Boolean, default=False)


class AppUser(Base):
    """A user of this application (admin or reviewer)."""

    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="reviewer")
    password_hash: Mapped[str] = mapped_column(String(300))
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarding_content_version: Mapped[int | None] = mapped_column(Integer)
    # Staff record used to track this user's own literacy path, if any.
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))


# Inventory -----------------------------------------------------------------

class Person(Base):
    """A staff member, contractor or other person operating AI on the organisation's behalf."""

    __tablename__ = "people"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), default="")
    department: Mapped[str] = mapped_column(String(200), default="")
    engagement: Mapped[str] = mapped_column(String(20), default="employee")  # employee | contractor | other
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Secret for the person's personal learning link (/learn/<token>); staff need no app account.
    learn_token: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: secrets.token_urlsafe(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assignments: Mapped[list["Assignment"]] = relationship(back_populates="person", cascade="all, delete-orphan")
    assessments: Mapped[list["Assessment"]] = relationship(
        back_populates="person", order_by="Assessment.created_at", cascade="all, delete-orphan"
    )
    requirements: Mapped[list["Requirement"]] = relationship(back_populates="person", cascade="all, delete-orphan")

    @property
    def latest_assessment(self) -> "Assessment | None":
        return self.assessments[-1] if self.assessments else None


class AISystem(Base):
    __tablename__ = "ai_systems"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    vendor: Mapped[str] = mapped_column(String(200), default="")
    org_role: Mapped[str] = mapped_column(String(20), default="deployer")
    risk_class: Mapped[str] = mapped_column(String(20), default="minimal")
    risk_class_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    generative: Mapped[bool] = mapped_column(Boolean, default=False)
    # Free-text list of affected groups, e.g. ["customers", "job candidates"].
    affected_persons: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    assignments: Mapped[list["Assignment"]] = relationship(back_populates="system", cascade="all, delete-orphan")


class Assignment(Base):
    """Links a person to an AI system with the role they play for it."""

    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("person_id", "system_id", "role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    system_id: Mapped[int] = mapped_column(ForeignKey("ai_systems.id"))
    role: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    person: Mapped[Person] = relationship(back_populates="assignments")
    system: Mapped[AISystem] = relationship(back_populates="assignments")


class Assessment(Base):
    """Contextual literacy needs assessment for one person (history kept)."""

    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    technical_background: Mapped[str] = mapped_column(String(20))
    ai_experience: Mapped[str] = mapped_column(String(20))
    education: Mapped[str] = mapped_column(String(300), default="")
    prior_training: Mapped[str] = mapped_column(Text, default="")
    context_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(200), default="")

    person: Mapped[Person] = relationship(back_populates="assessments")


# Content -------------------------------------------------------------------

class ContentModule(Base):
    __tablename__ = "content_modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    audience: Mapped[str] = mapped_column(String(30))  # core | role | affected | primer | app | sme
    versions: Mapped[list["ContentVersion"]] = relationship(
        back_populates="module", order_by="ContentVersion.version", cascade="all, delete-orphan"
    )

    @property
    def current(self) -> "ContentVersion":
        return self.versions[-1]


class ContentVersion(Base):
    """An immutable published version of a module's Markdown (+ quiz)."""

    __tablename__ = "content_versions"
    __table_args__ = (UniqueConstraint("module_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("content_modules.id"))
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    body_markdown: Mapped[str] = mapped_column(Text)
    quiz: Mapped[list] = mapped_column(JSON, default=list)
    sha256: Mapped[str] = mapped_column(String(64))
    material_change: Mapped[bool] = mapped_column(Boolean, default=False)
    change_note: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_by: Mapped[str] = mapped_column(String(200), default="system")

    module: Mapped[ContentModule] = relationship(back_populates="versions")


# Training ------------------------------------------------------------------

class Requirement(Base):
    """A training module a person is expected to take (one row per cycle)."""

    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    module_key: Mapped[str] = mapped_column(String(60))
    # Systems that make this module necessary for the person (ids).
    system_ids: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    trigger: Mapped[str] = mapped_column(String(30), default="initial")
    # initial | periodic | new_system | role_change | content_update
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    due_on: Mapped[date] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_version: Mapped[int | None] = mapped_column(Integer)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)

    person: Mapped[Person] = relationship(back_populates="requirements")

    def is_overdue(self, today: date) -> bool:
        return self.completed_at is None and not self.superseded and today > self.due_on


class QuizAttempt(Base):
    """Knowledge check attempt. Reinforcement only - never a pass/fail gate."""

    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    module_key: Mapped[str] = mapped_column(String(60))
    content_version: Mapped[int] = mapped_column(Integer)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    correct: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Reminder(Base):
    """Outbox of refresh reminders for delivery by e-mail/chat integrations."""

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"))
    kind: Mapped[str] = mapped_column(String(20))  # due_soon | overdue
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Evidence ------------------------------------------------------------------

class EvidenceEntry(Base):
    """Append-only, hash-chained record of every AI literacy measure.

    Rows are protected against UPDATE/DELETE at ORM level (see evidence.py)
    and by SQLite triggers created in db.init_db().
    """

    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, unique=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    measure_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    person_id: Mapped[int | None] = mapped_column(Integer)
    person_name: Mapped[str] = mapped_column(String(200), default="")
    system_ids: Mapped[list] = mapped_column(JSON, default=list)
    module_key: Mapped[str] = mapped_column(String(60), default="")
    content_version: Mapped[int | None] = mapped_column(Integer)
    measure_date: Mapped[date | None] = mapped_column(Date)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(200))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class IssuedDocument(Base):
    """PDF records/statements issued, for QR verification."""

    __tablename__ = "issued_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(40), unique=True)
    kind: Mapped[str] = mapped_column(String(30))  # training_record | measures_statement
    person_id: Mapped[int | None] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(String(300))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    issued_by: Mapped[str] = mapped_column(String(200))
    snapshot: Mapped[dict] = mapped_column(JSON)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    evidence_head_seq: Mapped[int] = mapped_column(Integer, default=0)
    evidence_head_hash: Mapped[str] = mapped_column(String(64), default="")
