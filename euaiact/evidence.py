"""Evidence register: append-only, hash-chained log of AI literacy measures.

Each entry's hash covers its content plus the previous entry's hash, so any
later modification or removal breaks the chain and is detected by
verify_chain(). Updates and deletes are also blocked by an ORM guard here and
by database triggers (db.init_db).
"""

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from .models import MEASURE_TYPES, EvidenceEntry, IssuedDocument, utcnow

GENESIS_HASH = "0" * 64
_CHAIN_LOCK = 0x4A4C4954  # arbitrary advisory lock id for the evidence chain


class ImmutableRecordError(Exception):
    pass


@event.listens_for(Session, "before_flush")
def _guard_append_only(session: Session, _ctx, _instances) -> None:
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj, (EvidenceEntry, IssuedDocument)) and (obj in session.deleted or session.is_modified(obj)):
            raise ImmutableRecordError(f"{type(obj).__name__} records are append-only")


def _canonical(entry: EvidenceEntry) -> str:
    payload = {
        "seq": entry.seq,
        "recorded_at": entry.recorded_at.isoformat(),
        "measure_type": entry.measure_type,
        "title": entry.title,
        "description": entry.description,
        "person_id": entry.person_id,
        "person_name": entry.person_name,
        "system_ids": list(entry.system_ids or []),
        "module_key": entry.module_key,
        "content_version": entry.content_version,
        "measure_date": entry.measure_date.isoformat() if entry.measure_date else None,
        "details": entry.details or {},
        "actor": entry.actor,
        "prev_hash": entry.prev_hash,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_hash(entry: EvidenceEntry) -> str:
    return hashlib.sha256(_canonical(entry).encode("utf-8")).hexdigest()


def head(session: Session) -> EvidenceEntry | None:
    return session.scalars(select(EvidenceEntry).order_by(EvidenceEntry.seq.desc()).limit(1)).first()


def record(
    session: Session,
    measure_type: str,
    title: str,
    actor: str,
    *,
    description: str = "",
    person=None,
    system_ids: list[int] | None = None,
    module_key: str = "",
    content_version: int | None = None,
    measure_date: date | None = None,
    details: dict | None = None,
) -> EvidenceEntry:
    if measure_type not in MEASURE_TYPES:
        raise ValueError(f"unknown measure type: {measure_type}")
    session.flush()
    if session.get_bind().dialect.name == "postgresql":
        # Serialise writers so two transactions cannot both extend the chain from the same head.
        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK})
    last = head(session)
    recorded_at = utcnow()
    entry = EvidenceEntry(
        seq=(last.seq + 1) if last else 1,
        recorded_at=recorded_at,
        measure_type=measure_type,
        title=title,
        description=description,
        person_id=person.id if person is not None else None,
        person_name=person.name if person is not None else "",
        system_ids=sorted(system_ids or []),
        module_key=module_key,
        content_version=content_version,
        measure_date=measure_date or recorded_at.date(),
        details=details or {},
        actor=actor,
        prev_hash=last.hash if last else GENESIS_HASH,
    )
    entry.hash = compute_hash(entry)
    session.add(entry)
    session.flush()
    return entry


@dataclass
class ChainReport:
    ok: bool
    entries: int
    first_broken_seq: int | None = None
    problem: str = ""


def verify_chain(session: Session) -> ChainReport:
    prev = GENESIS_HASH
    expected_seq = 1
    count = 0
    for entry in session.scalars(select(EvidenceEntry).order_by(EvidenceEntry.seq)):
        count += 1
        if entry.seq != expected_seq:
            return ChainReport(False, count, entry.seq, f"sequence gap: expected {expected_seq}")
        if entry.prev_hash != prev:
            return ChainReport(False, count, entry.seq, "previous-hash link broken")
        if compute_hash(entry) != entry.hash:
            return ChainReport(False, count, entry.seq, "content does not match stored hash")
        prev = entry.hash
        expected_seq += 1
    return ChainReport(True, count)


def count(session: Session) -> int:
    return session.scalar(select(func.count(EvidenceEntry.id))) or 0


CSV_COLUMNS = [
    "seq", "recorded_at_utc", "measure_type", "measure_label", "measure_date", "title", "description",
    "person_id", "person_name", "system_ids", "module_key", "content_version", "actor", "details",
    "prev_hash", "hash",
]


def _fmt_ts(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def export_csv(entries: list[EvidenceEntry]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for e in entries:
        writer.writerow([
            e.seq, _fmt_ts(e.recorded_at), e.measure_type, MEASURE_TYPES.get(e.measure_type, e.measure_type),
            e.measure_date.isoformat() if e.measure_date else "", e.title, e.description,
            e.person_id or "", e.person_name, " ".join(str(s) for s in e.system_ids or []), e.module_key,
            e.content_version or "", e.actor, json.dumps(e.details or {}, sort_keys=True, ensure_ascii=False),
            e.prev_hash, e.hash,
        ])
    return buf.getvalue()
