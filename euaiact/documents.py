"""AI Literacy Training Record (individual) and Article 4 Measures Statement (organisation).

Both are PDFs with a unique ID and a QR code linking to /verify/<id>. The
wording deliberately documents *measures taken*; the AI Act prescribes no
AI literacy certificate, so these documents never claim to certify
competence or legal compliance. tests/test_documents.py guards the wording.
"""

import hashlib
import io
import json
import secrets
from datetime import date

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import evidence
from .assessment import build_learning_path
from .content import all_modules, get_module
from .dashboard import build_dashboard
from .db import get_org
from .models import (
    MEASURE_TYPES,
    STAFF_ROLES,
    EvidenceEntry,
    IssuedDocument,
    Person,
    utcnow,
)
from .refresh import latest_requirement, module_status

RECORD_TITLE = "AI Literacy Training Record"
STATEMENT_TITLE = "Article 4 Measures Statement"

LEGAL_BASIS = (
    "Article 4 of Regulation (EU) 2024/1689 (AI Act), as amended by Regulation (EU) 2026/1744 "
    "(Digital Omnibus): providers and deployers take measures to support the development of AI "
    "literacy of their staff and other persons dealing with the operation and use of AI systems on "
    "their behalf, taking into account their technical knowledge, experience, education and training, "
    "the context the AI systems are used in, and the persons on whom they are used."
)

NOT_A_CERTIFICATE = (
    "This document records measures taken to support AI literacy. It is not a certificate: it does not "
    "attest to any individual's competence or level of AI literacy, and it does not certify compliance "
    "with the AI Act or any other law. The AI Act does not prescribe an AI literacy certificate and "
    "does not require any specific individual level of AI literacy to be guaranteed. Knowledge checks "
    "mentioned here serve learning reinforcement only and are not pass/fail assessments."
)

NON_TRAINING_MEASURES = ("policy_issued", "awareness_session", "guidance_doc", "other_measure")


def new_doc_id(prefix: str) -> str:
    raw = secrets.token_hex(6).upper()
    return f"{prefix}-{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def _sha(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _issue(session: Session, kind: str, prefix: str, subject: str, snapshot: dict, actor: str,
           person: Person | None = None) -> IssuedDocument:
    doc_id = new_doc_id(prefix)
    head = evidence.head(session)
    snapshot = {**snapshot, "doc_id": doc_id}
    doc = IssuedDocument(
        doc_id=doc_id, kind=kind, person_id=person.id if person else None, subject=subject,
        issued_by=actor, snapshot=snapshot, snapshot_sha256=_sha(snapshot),
        evidence_head_seq=head.seq if head else 0, evidence_head_hash=head.hash if head else evidence.GENESIS_HASH,
    )
    session.add(doc)
    session.flush()
    evidence.record(
        session, "document_issued", f"{snapshot['title']} {doc_id} issued", actor, person=person,
        details={"doc_id": doc_id, "kind": kind, "snapshot_sha256": doc.snapshot_sha256},
    )
    return doc


def issue_training_record(session: Session, person: Person, actor: str) -> IssuedDocument:
    org = get_org(session)
    today = utcnow().date()
    path = build_learning_path(person, sme_mode=org.sme_mode)
    completed = sorted(
        (r for r in person.requirements if r.completed_at is not None),
        key=lambda r: r.completed_at,
    )
    rows = []
    for r in completed:
        module = get_module(session, r.module_key)
        rows.append({
            "module": module.title if module else r.module_key,
            "module_key": r.module_key,
            "version": r.completed_version,
            "completed_on": r.completed_at.date().isoformat(),
            "trigger": r.trigger,
        })
    outstanding = []
    for item in path.items:
        if item.optional:
            continue
        status = module_status(session, person, item.module_key, today)
        if status != "current":
            req = latest_requirement(person, item.module_key)
            module = get_module(session, item.module_key)
            outstanding.append({
                "module": module.title if module else item.module_key,
                "status": status,
                "due_on": req.due_on.isoformat() if req and req.completed_at is None else "",
            })
    snapshot = {
        "title": RECORD_TITLE,
        "organisation": org.org_name,
        "person": {"id": person.id, "name": person.name, "department": person.department,
                   "engagement": person.engagement},
        "ai_systems": [{"system": a.system.name, "role": STAFF_ROLES.get(a.role, a.role),
                        "risk_class": a.system.risk_class} for a in person.assignments],
        "learning_path_depth": path.depth,
        "trainings_completed": rows,
        "outstanding": outstanding,
        "refresh_interval_months": org.refresh_interval_months,
        "issued_on": today.isoformat(),
    }
    return _issue(session, "training_record", "ALR", person.name, snapshot, actor, person)


def issue_measures_statement(session: Session, actor: str, period_start: date | None = None) -> IssuedDocument:
    org = get_org(session)
    today = utcnow().date()
    dash = build_dashboard(session, today)
    q = select(EvidenceEntry).order_by(EvidenceEntry.seq)
    entries = [e for e in session.scalars(q) if period_start is None or e.measure_date >= period_start]
    counts = {}
    for e in entries:
        counts[e.measure_type] = counts.get(e.measure_type, 0) + 1
    other = [
        {"date": e.measure_date.isoformat(), "type": MEASURE_TYPES[e.measure_type], "title": e.title,
         "evidence_seq": e.seq}
        for e in entries if e.measure_type in NON_TRAINING_MEASURES
    ]
    snapshot = {
        "title": STATEMENT_TITLE,
        "organisation": org.org_name,
        "period": {"from": period_start.isoformat() if period_start else "programme start", "to": today.isoformat()},
        "programme": {
            "refresh_interval_months": org.refresh_interval_months,
            "sme_mode": org.sme_mode,
            "content": [{"module": m.title, "version": m.current.version,
                         "published": m.current.published_at.date().isoformat()} for m in all_modules(session)],
        },
        "counts": {MEASURE_TYPES[k]: v for k, v in sorted(counts.items())},
        "other_measures": other,
        "coverage": {
            "people_in_scope": dash.people_total,
            "people_with_all_required_modules_current": dash.people_covered,
            "percent": dash.staff_percent,
            "systems": [{"system": c.system.name, "risk_class": c.system.risk_class, "people": c.people,
                         "covered": c.covered, "percent": c.percent} for c in dash.systems],
            "overdue_items": len(dash.overdue),
        },
        "evidence_register": {"entries": dash.evidence_entries, "integrity_ok": dash.chain_ok},
        "issued_on": today.isoformat(),
    }
    return _issue(session, "measures_statement", "A4S", org.org_name, snapshot, actor)


# PDF rendering ------------------------------------------------------------

def verify_url(base_url: str, doc_id: str) -> str:
    return f"{base_url}/verify/{doc_id}"


def _qr(url: str, size=32 * mm) -> Drawing:
    widget = QrCodeWidget(url)
    x1, y1, x2, y2 = widget.getBounds()
    d = Drawing(size, size, transform=[size / (x2 - x1), 0, 0, size / (y2 - y1), 0, 0])
    d.add(widget)
    return d


def _table(rows: list[list], widths=None) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf5")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b8c2d3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def render_pdf(doc: IssuedDocument, base_url: str) -> bytes:
    snap = doc.snapshot
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=10, textColor=colors.HexColor("#444444"))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11, spaceBefore=8)
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"{snap['title']} {doc.doc_id}",
                            author=snap["organisation"], subject=snap["title"])
    url = verify_url(base_url, doc.doc_id)
    header = Table([[
        [Paragraph(f"<b>{_e(snap['title'])}</b>", styles["Title"]),
         Paragraph(f"{_e(snap['organisation'])}", body),
         Paragraph(f"Document ID: <b>{doc.doc_id}</b> &nbsp; Issued: {snap['issued_on']}", body),
         Paragraph(f"Verify: {_e(url)}", small)],
        _qr(url),
    ]], colWidths=[140 * mm, 34 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story = [header, Spacer(1, 4 * mm), Paragraph(_e(NOT_A_CERTIFICATE), small), Spacer(1, 2 * mm)]

    if doc.kind == "training_record":
        p = snap["person"]
        story += [
            Paragraph("Person", h2),
            Paragraph(f"{_e(p['name'])} &middot; {_e(p['department'] or '-')} &middot; {_e(p['engagement'])}", body),
            Paragraph(f"Learning path depth: {_e(snap['learning_path_depth'])}. Refresh interval: "
                      f"{snap['refresh_interval_months']} months.", body),
            Paragraph("AI systems and roles", h2),
            _table([["AI system", "Role", "Risk class"]] +
                   ([[_p(s["system"], body), s["role"], s["risk_class"]] for s in snap["ai_systems"]]
                    or [["None linked", "-", "-"]]), [90 * mm, 45 * mm, 39 * mm]),
            Paragraph("Training measures completed", h2),
            _table([["Module", "Content version", "Completed", "Trigger"]] +
                   ([[_p(r["module"], body), f"v{r['version']}", r["completed_on"], r["trigger"].replace("_", " ")]
                     for r in snap["trainings_completed"]] or [["None recorded yet", "", "", ""]]),
                   [84 * mm, 28 * mm, 30 * mm, 32 * mm]),
        ]
        if snap["outstanding"]:
            story += [Paragraph("Outstanding at time of issue", h2),
                      _table([["Module", "Status", "Due"]] +
                             [[_p(o["module"], body), o["status"], o["due_on"]] for o in snap["outstanding"]],
                             [100 * mm, 40 * mm, 34 * mm])]
    else:
        c = snap["coverage"]
        story += [
            Paragraph("Period", h2),
            Paragraph(f"{snap['period']['from']} to {snap['period']['to']}", body),
            Paragraph("Measures taken", h2),
            _table([["Measure", "Count"]] + [[k, str(v)] for k, v in snap["counts"].items()], [140 * mm, 34 * mm]),
            Paragraph("Coverage of staff and other persons in scope", h2),
            Paragraph(f"{c['people_with_all_required_modules_current']} of {c['people_in_scope']} persons "
                      f"({c['percent']}%) had all required training measures current on the date of issue. "
                      f"Overdue items: {c['overdue_items']}.", body),
            _table([["AI system", "Risk class", "Persons", "Current", "%"]] +
                   ([[_p(s["system"], body), s["risk_class"], s["people"], s["covered"], f"{s['percent']}%"]
                     for s in c["systems"]] or [["-"] * 5]), [70 * mm, 36 * mm, 22 * mm, 22 * mm, 24 * mm]),
            Paragraph("Policies, awareness sessions and guidance", h2),
            _table([["Date", "Type", "Measure", "Evidence #"]] +
                   ([[o["date"], _p(o["type"], body), _p(o["title"], body), str(o["evidence_seq"])]
                     for o in snap["other_measures"]] or [["-", "-", "None recorded", "-"]]),
                   [24 * mm, 45 * mm, 85 * mm, 20 * mm]),
            Paragraph("Training content in use", h2),
            _table([["Module", "Version", "Published"]] +
                   [[_p(m["module"], body), f"v{m['version']}", m["published"]] for m in snap["programme"]["content"]],
                   [120 * mm, 24 * mm, 30 * mm]),
            Paragraph(f"Evidence register: {snap['evidence_register']['entries']} entries, integrity check "
                      f"{'passed' if snap['evidence_register']['integrity_ok'] else 'FAILED'} at issue.", body),
        ]
    story += [
        Spacer(1, 4 * mm),
        Paragraph("Legal basis", h2),
        Paragraph(_e(LEGAL_BASIS), small),
        Paragraph(f"Snapshot SHA-256: {doc.snapshot_sha256}<br/>Evidence register head at issue: "
                  f"#{doc.evidence_head_seq} {doc.evidence_head_hash}", small),
    ]
    pdf.build(story)
    return buf.getvalue()


def _e(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _p(text, style) -> Paragraph:
    return Paragraph(_e(text), style)


def document_text(doc: IssuedDocument) -> str:
    """Plain text of the fixed wording on a document (used by wording tests)."""
    return "\n".join([doc.snapshot["title"], NOT_A_CERTIFICATE, LEGAL_BASIS])


def find(session: Session, doc_id: str) -> IssuedDocument | None:
    return session.scalars(select(IssuedDocument).where(IssuedDocument.doc_id == doc_id)).first()


def verify(session: Session, doc: IssuedDocument) -> dict:
    anchor = session.scalars(select(EvidenceEntry).where(EvidenceEntry.seq == doc.evidence_head_seq)).first()
    anchored = doc.evidence_head_seq == 0 or (anchor is not None and anchor.hash == doc.evidence_head_hash)
    return {
        "snapshot_intact": _sha(doc.snapshot) == doc.snapshot_sha256,
        "evidence_anchor_intact": anchored,
    }


def render_evidence_pdf(entries: list[EvidenceEntry], org_name: str, chain: "evidence.ChainReport",
                        filters: str = "") -> bytes:
    """Evidence register export for market surveillance authorities."""
    from reportlab.lib.pagesizes import landscape

    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=7, leading=8.5)
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm, title=f"AI literacy evidence register - {org_name}")
    generated = utcnow().strftime("%Y-%m-%d %H:%M UTC")
    story = [
        Paragraph(f"AI literacy evidence register (Art. 4) - {_e(org_name)}", styles["Title"]),
        Paragraph(f"Exported {generated}. {len(entries)} entries{(' (filter: ' + _e(filters) + ')') if filters else ''}. "
                  f"Integrity check of the full register: {'PASSED' if chain.ok else 'FAILED at #' + str(chain.first_broken_seq)} "
                  f"({chain.entries} entries). Each entry's SHA-256 hash covers its content and the previous "
                  f"entry's hash; entries cannot be modified or deleted.", small),
        Spacer(1, 3 * mm),
    ]
    rows = [["#", "Recorded (UTC)", "Measure date", "Type", "Title / description", "Person", "Module (ver.)", "Actor", "Hash"]]
    for e in entries:
        rows.append([
            str(e.seq), e.recorded_at.strftime("%Y-%m-%d %H:%M:%S"),
            e.measure_date.isoformat() if e.measure_date else "",
            _p(MEASURE_TYPES.get(e.measure_type, e.measure_type), small),
            _p(e.title + (f" - {e.description}" if e.description else ""), small),
            _p(e.person_name, small),
            _p(f"{e.module_key} (v{e.content_version})" if e.module_key and e.content_version else e.module_key, small),
            _p(e.actor, small), _p(e.hash[:16] + "...", small),
        ])
    t = _table(rows, [9 * mm, 27 * mm, 19 * mm, 33 * mm, 82 * mm, 28 * mm, 30 * mm, 26 * mm, 23 * mm])
    t.setStyle(TableStyle([("FONT", (0, 1), (-1, -1), "Helvetica", 7)]))
    story.append(t)
    pdf.build(story)
    return buf.getvalue()
