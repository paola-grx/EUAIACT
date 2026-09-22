import re

from euaiact import documents, inventory, refresh
from euaiact.models import IssuedDocument


def make_person(session):
    p = inventory.add_person(session, "t", name="Rita Record", department="Sales")
    s = inventory.add_system(session, "t", name="Chat", risk_class="limited", generative=True)
    inventory.assign(session, p, s, "operator", "t")
    for r in list(p.requirements):
        refresh.complete_requirement(session, r, 1, "t")
    return p


def test_wording_documents_measures_not_competence():
    for title in (documents.RECORD_TITLE, documents.STATEMENT_TITLE):
        assert "certif" not in title.lower()
    text = documents.NOT_A_CERTIFICATE
    assert "records measures taken to support AI literacy" in text
    assert "not a certificate" in text
    assert "does not certify compliance" in text
    assert "does not prescribe an AI literacy certificate" in text
    # Every mention of certify/certificate in the fixed wording must be negated.
    for sentence in re.split(r"(?<=[.:])\s+", text + " " + documents.LEGAL_BASIS):
        if "certif" in sentence.lower():
            assert re.search(r"\bnot\b|\bno\b", sentence), sentence


def test_training_record_pdf_with_unique_id_and_qr(session):
    p = make_person(session)
    doc = documents.issue_training_record(session, p, "admin")
    other = documents.issue_training_record(session, p, "admin")
    assert re.fullmatch(r"ALR-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}", doc.doc_id)
    assert doc.doc_id != other.doc_id
    assert {r["module_key"] for r in doc.snapshot["trainings_completed"]} == {"core", "role-genai-user"}
    pdf = documents.render_pdf(doc, "https://x.example")
    assert pdf.startswith(b"%PDF")
    assert documents.verify(session, doc) == {"snapshot_intact": True, "evidence_anchor_intact": True}


def test_measures_statement(session):
    make_person(session)
    from euaiact import evidence

    evidence.record(session, "policy_issued", "AI usage policy v1", "admin")
    doc = documents.issue_measures_statement(session, "admin")
    assert doc.doc_id.startswith("A4S-")
    assert doc.snapshot["coverage"]["people_in_scope"] == 1
    assert doc.snapshot["other_measures"][0]["title"] == "AI usage policy v1"
    assert documents.render_pdf(doc, "https://x.example").startswith(b"%PDF")
    assert session.query(IssuedDocument).count() == 1


def test_evidence_pdf_export(session):
    make_person(session)
    from euaiact import evidence
    from euaiact.models import EvidenceEntry

    pdf = documents.render_evidence_pdf(session.query(EvidenceEntry).all(), "Acme", evidence.verify_chain(session))
    assert pdf.startswith(b"%PDF")
