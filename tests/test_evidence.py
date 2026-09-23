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
    if session.get_bind().dialect.name == "postgresql":
        with pytest.raises(IntegrityError):
            session.execute(text("TRUNCATE evidence"))
        session.rollback()


def test_tampering_detected(session):
    evidence.record(session, "guidance_doc", "Prompting guide", "admin")
    evidence.record(session, "awareness_session", "Lunch & learn", "admin")
    session.commit()
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("ALTER TABLE evidence DISABLE TRIGGER USER"))
    else:
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


def test_concurrent_writers_keep_chain_intact(session):
    """Parallel transactions must not fork the chain (PostgreSQL advisory lock)."""
    from concurrent.futures import ThreadPoolExecutor

    from euaiact.db import make_sessionmaker

    engine = session.get_bind()
    if engine.dialect.name != "postgresql":
        pytest.skip("SQLite serialises writers itself; this exercises the PostgreSQL lock")
    session.commit()
    Session = make_sessionmaker(engine)

    def writer(i):
        for j in range(10):
            with Session() as s:
                evidence.record(s, "other_measure", f"w{i}-{j}", "t")
                s.commit()

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(writer, range(8)))
    report = evidence.verify_chain(session)
    assert report.ok and report.entries >= 80
