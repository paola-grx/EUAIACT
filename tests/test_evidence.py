import csv
import io

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from euaiact import evidence, inventory
from euaiact.evidence import ImmutableRecordError
from euaiact.models import EvidenceEntry


def test_every_measure_is_logged_and_chained(session):
    p = inventory.add_person(session, "t", name="A")
    evidence.record(session, "policy_issued", "AI policy v1", "admin")
    report = evidence.verify_chain(session)
    assert report.ok and report.entries >= 4
    entries = session.query(EvidenceEntry).order_by(EvidenceEntry.seq).all()
    assert entries[0].prev_hash == evidence.GENESIS_HASH
    assert all(b.prev_hash == a.hash for a, b in zip(entries, entries[1:]))
    assert any(e.measure_type == "training_assigned" and e.person_id == p.id for e in entries)


def test_orm_update_and_delete_blocked(session):
    e = evidence.record(session, "guidance_doc", "Prompting guide", "admin")
    session.commit()
    e.title = "changed"
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()
    session.delete(session.get(EvidenceEntry, e.id))
    with pytest.raises(ImmutableRecordError):
        session.flush()
    session.rollback()


def test_database_trigger_blocks_raw_sql(session):
    evidence.record(session, "guidance_doc", "Prompting guide", "admin")
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(text("UPDATE evidence SET title = 'x'"))
    session.rollback()
    with pytest.raises(IntegrityError):
        session.execute(text("DELETE FROM evidence"))
    session.rollback()


def test_tampering_detected(session):
    evidence.record(session, "guidance_doc", "Prompting guide", "admin")
    evidence.record(session, "awareness_session", "Lunch & learn", "admin")
    session.commit()
    session.execute(text("DROP TRIGGER evidence_no_update"))
    session.execute(text("UPDATE evidence SET title = 'forged' WHERE seq = 1"))
    session.commit()
    session.expire_all()
    report = evidence.verify_chain(session)
    assert not report.ok and report.first_broken_seq == 1


def test_csv_export(session):
    evidence.record(session, "awareness_session", "Lunch & learn", "admin", details={"attendees": ["A", "B"]})
    rows = list(csv.DictReader(io.StringIO(evidence.export_csv(session.query(EvidenceEntry).all()))))
    row = [r for r in rows if r["measure_type"] == "awareness_session"][0]
    assert row["measure_label"] == "Awareness session held"
    assert row["recorded_at_utc"].endswith("Z") and len(row["hash"]) == 64
