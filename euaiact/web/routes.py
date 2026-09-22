"""HTTP routes."""

from datetime import date

import yaml
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import classification, content, dashboard, documents, evidence, inventory, refresh
from ..assessment import APP_ONBOARDING, build_learning_path
from ..auth import check_password, hash_password
from ..db import get_org
from ..models import (
    MEASURE_TYPES,
    STAFF_ROLES,
    AISystem,
    AppUser,
    Assignment,
    EvidenceEntry,
    IssuedDocument,
    Person,
    QuizAttempt,
    Reminder,
    Requirement,
    utcnow,
)
from .app import ONBOARDING_EXEMPT, NeedsLogin, NeedsOnboarding

router = APIRouter()

# Measures an admin can record by hand (the rest are written by the app).
MANUAL_MEASURES = ["policy_issued", "awareness_session", "guidance_doc", "training_completed", "other_measure"]


# Dependencies --------------------------------------------------------------

def db(request: Request):
    with request.app.state.Session() as session:
        yield session


def onboarding_done(session: Session, user: AppUser) -> bool:
    module = content.get_module(session, APP_ONBOARDING)
    if module is None:
        return True
    return (user.onboarding_content_version or 0) >= content.required_onboarding_version(module)


def current_user(request: Request, session: Session = Depends(db)) -> AppUser:
    uid = request.session.get("uid")
    user = session.get(AppUser, uid) if uid else None
    if user is None:
        raise NeedsLogin()
    if not request.url.path.startswith(ONBOARDING_EXEMPT) and not onboarding_done(session, user):
        raise NeedsOnboarding()
    return user


def admin_user(user: AppUser = Depends(current_user)) -> AppUser:
    if user.role != "admin":
        raise HTTPException(403, "Administrator role required")
    return user


def actor(user: AppUser) -> str:
    return f"{user.name} <{user.email}>"


def render(request: Request, template: str, status_code: int = 200, **ctx) -> HTMLResponse:
    templates = request.app.state.templates
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def get_or_404(session: Session, model, ident):
    obj = session.get(model, ident)
    if obj is None:
        raise HTTPException(404)
    return obj


# Setup & auth -------------------------------------------------------------

@router.get("/setup")
def setup_form(request: Request, session: Session = Depends(db)):
    if session.scalar(select(func.count(AppUser.id))):
        return redirect("/login")
    return render(request, "setup.html", user=None)


@router.post("/setup")
def setup(request: Request, session: Session = Depends(db), org_name: str = Form(...), name: str = Form(...),
          email: str = Form(...), password: str = Form(...)):
    if session.scalar(select(func.count(AppUser.id))):
        raise HTTPException(403, "Already set up")
    if len(password) < 10:
        return render(request, "setup.html", 400, user=None, error="Password must have at least 10 characters.")
    get_org(session).org_name = org_name.strip()
    user = AppUser(name=name.strip(), email=email.strip().lower(), role="admin", password_hash=hash_password(password))
    session.add(user)
    session.flush()
    evidence.record(session, "settings_changed", f"Programme set up for {org_name}", actor(user),
                    details={"first_admin": user.email})
    session.commit()
    request.session["uid"] = user.id
    return redirect("/onboarding")


@router.get("/login")
def login_form(request: Request, session: Session = Depends(db)):
    if not session.scalar(select(func.count(AppUser.id))):
        return redirect("/setup")
    return render(request, "login.html", user=None)


@router.post("/login")
def login(request: Request, session: Session = Depends(db), email: str = Form(...), password: str = Form(...)):
    user = session.scalars(select(AppUser).where(AppUser.email == email.strip().lower())).first()
    if user is None or not check_password(password, user.password_hash):
        return render(request, "login.html", 400, user=None, error="Unknown e-mail or wrong password.")
    request.session["uid"] = user.id
    return redirect("/")


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


# App's own Art. 4 onboarding & guidance -----------------------------------

@router.get("/onboarding")
def onboarding(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    module = content.get_module(session, APP_ONBOARDING)
    return render(request, "onboarding.html", user=user, module=module, version=module.current,
                  done=onboarding_done(session, user), results=None)


@router.post("/onboarding/quiz")
async def onboarding_quiz(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    module = content.get_module(session, APP_ONBOARDING)
    form = await request.form()
    results = content.score_quiz(module.current.quiz, dict(form))
    return render(request, "onboarding.html", user=user, module=module, version=module.current,
                  done=onboarding_done(session, user), results=results)


@router.post("/onboarding/complete")
def onboarding_complete(session: Session = Depends(db), user: AppUser = Depends(current_user),
                        confirm: str = Form("")):
    if confirm != "yes":
        return redirect("/onboarding")
    module = content.get_module(session, APP_ONBOARDING)
    user.onboarding_completed_at = utcnow()
    user.onboarding_content_version = module.current.version
    evidence.record(session, "training_completed",
                    f"App onboarding v{module.current.version} completed by {user.name} ({user.role})", actor(user),
                    module_key=APP_ONBOARDING, content_version=module.current.version,
                    details={"app_user": user.email, "app_role": user.role})
    session.commit()
    return redirect("/")


@router.get("/guidance/automation-limits")
def automation_limits(request: Request, user: AppUser = Depends(current_user)):
    return render(request, "guidance.html", user=user, limits=classification.LIMITS)


@router.get("/legal-dates")
def legal_dates(request: Request, user: AppUser = Depends(current_user)):
    return render(request, "legal_dates.html", user=user, milestones=request.app.state.milestones,
                  today=utcnow().date())


# Dashboard -----------------------------------------------------------------

@router.get("/")
def home(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    return render(request, "dashboard.html", user=user, d=dashboard.build_dashboard(session), org=get_org(session))


# People --------------------------------------------------------------------

@router.get("/people")
def people(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    org = get_org(session)
    rows = []
    today = utcnow().date()
    for p in session.scalars(select(Person).order_by(Person.active.desc(), Person.name)):
        path = build_learning_path(p, sme_mode=org.sme_mode)
        statuses = [refresh.module_status(session, p, k, today) for k in path.required_keys()]
        rows.append((p, path, statuses))
    return render(request, "people.html", user=user, rows=rows)


@router.post("/people")
def people_add(session: Session = Depends(db), user: AppUser = Depends(admin_user), name: str = Form(...),
               email: str = Form(""), department: str = Form(""), engagement: str = Form("employee")):
    person = inventory.add_person(session, actor(user), name=name.strip(), email=email.strip(),
                                  department=department.strip(), engagement=engagement)
    session.commit()
    return redirect(f"/people/{person.id}")


@router.get("/people/{pid}")
def person_detail(request: Request, pid: int, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    person = get_or_404(session, Person, pid)
    org = get_org(session)
    path = build_learning_path(person, sme_mode=org.sme_mode)
    today = utcnow().date()
    modules = {m.key: m for m in content.all_modules(session)}
    items = [(i, modules.get(i.module_key), refresh.module_status(session, person, i.module_key, today),
              refresh.latest_requirement(person, i.module_key)) for i in path.items]
    history = sorted(person.requirements, key=lambda r: (r.assigned_at, r.id), reverse=True)
    docs = session.scalars(select(IssuedDocument).where(IssuedDocument.person_id == person.id)
                           .order_by(IssuedDocument.issued_at.desc())).all()
    systems = session.scalars(select(AISystem).order_by(AISystem.name)).all()
    learn_url = f"{request.app.state.settings.base_url}/learn/{person.learn_token}"
    return render(request, "person.html", user=user, person=person, path=path, items=items, history=history,
                  docs=docs, systems=systems, modules=modules, learn_url=learn_url, today=today)


@router.post("/people/{pid}/assessment")
def person_assessment(pid: int, session: Session = Depends(db), user: AppUser = Depends(admin_user),
                      technical_background: str = Form(...), ai_experience: str = Form(...),
                      education: str = Form(""), prior_training: str = Form(""), context_notes: str = Form("")):
    person = get_or_404(session, Person, pid)
    inventory.record_assessment(session, person, actor(user), technical_background=technical_background,
                                ai_experience=ai_experience, education=education, prior_training=prior_training,
                                context_notes=context_notes)
    session.commit()
    return redirect(f"/people/{pid}")


@router.post("/people/{pid}/assign")
def person_assign(pid: int, session: Session = Depends(db), user: AppUser = Depends(admin_user),
                  system_id: int = Form(...), role: str = Form(...)):
    _assign(session, user, pid, system_id, role)
    return redirect(f"/people/{pid}")


@router.post("/systems/{sid}/assign")
def system_assign(sid: int, session: Session = Depends(db), user: AppUser = Depends(admin_user),
                  person_id: int = Form(...), role: str = Form(...)):
    _assign(session, user, person_id, sid, role)
    return redirect(f"/systems/{sid}")


def _assign(session: Session, user: AppUser, pid: int, sid: int, role: str) -> None:
    if role not in STAFF_ROLES:
        raise HTTPException(400, "Unknown role")
    inventory.assign(session, get_or_404(session, Person, pid), get_or_404(session, AISystem, sid), role, actor(user))
    session.commit()


@router.post("/assignments/{aid}/delete")
def assignment_delete(aid: int, session: Session = Depends(db), user: AppUser = Depends(admin_user),
                      back: str = Form("")):
    assignment = get_or_404(session, Assignment, aid)
    pid = assignment.person_id
    inventory.unassign(session, assignment, actor(user))
    session.commit()
    return redirect(back if back.startswith("/systems/") else f"/people/{pid}")


@router.post("/people/{pid}/requirements/{rid}/complete")
def requirement_complete(pid: int, rid: int, session: Session = Depends(db), user: AppUser = Depends(admin_user),
                         completed_on: date = Form(...), method: str = Form(...), note: str = Form("")):
    req = get_or_404(session, Requirement, rid)
    if req.person_id != pid:
        raise HTTPException(404)
    if completed_on > utcnow().date():
        raise HTTPException(400, "Completion date cannot be in the future")
    module = content.get_module(session, req.module_key)
    refresh.complete_requirement(session, req, module.current.version, actor(user), completed_on=completed_on,
                                 method=method, note=note)
    session.commit()
    return redirect(f"/people/{pid}")


@router.post("/people/{pid}/active")
def person_active(pid: int, session: Session = Depends(db), user: AppUser = Depends(admin_user),
                  active: str = Form(...)):
    person = get_or_404(session, Person, pid)
    person.active = active == "yes"
    evidence.record(session, "inventory_change", f"{person.name} marked {'active' if person.active else 'inactive'}",
                    actor(user), person=person)
    session.commit()
    return redirect(f"/people/{pid}")


@router.post("/people/{pid}/record")
def person_record(pid: int, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    person = get_or_404(session, Person, pid)
    doc = documents.issue_training_record(session, person, actor(user))
    session.commit()
    return redirect(f"/documents/{doc.doc_id}.pdf")


# AI systems ----------------------------------------------------------------

def _affected(raw: str) -> list[str]:
    return [a.strip() for a in raw.replace("\n", ",").split(",") if a.strip()]


@router.get("/systems")
def systems(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    rows = session.scalars(select(AISystem).order_by(AISystem.name)).all()
    return render(request, "systems.html", user=user, systems=rows, areas=classification.ANNEX_III_AREAS,
                  suggestion=None, prefill={})


@router.post("/systems/classify")
async def systems_classify(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    form = await request.form()
    suggestion = classification.suggest(
        annex_iii_areas=form.getlist("annex_iii"),
        annex_i_product=form.get("annex_i") == "yes",
        interacts_with_people=form.get("interacts") == "yes",
        generates_content=form.get("generates") == "yes",
        general_purpose=form.get("general_purpose") == "yes",
    )
    rows = session.scalars(select(AISystem).order_by(AISystem.name)).all()
    return render(request, "systems.html", user=user, systems=rows, areas=classification.ANNEX_III_AREAS,
                  suggestion=suggestion, prefill=dict(form))


@router.post("/systems")
def systems_add(session: Session = Depends(db), user: AppUser = Depends(admin_user), name: str = Form(...),
                description: str = Form(""), vendor: str = Form(""), org_role: str = Form("deployer"),
                risk_class: str = Form("minimal"), generative: str = Form(""), affected_persons: str = Form("")):
    system = inventory.add_system(session, actor(user), name=name.strip(), description=description.strip(),
                                  vendor=vendor.strip(), org_role=org_role, risk_class=risk_class,
                                  generative=generative == "yes", affected_persons=_affected(affected_persons))
    session.commit()
    return redirect(f"/systems/{system.id}")


@router.get("/systems/{sid}")
def system_detail(request: Request, sid: int, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    system = get_or_404(session, AISystem, sid)
    people = session.scalars(select(Person).where(Person.active.is_(True)).order_by(Person.name)).all()
    d = dashboard.build_dashboard(session)
    cov = next((c for c in d.systems if c.system.id == sid), None)
    return render(request, "system.html", user=user, system=system, people=people, coverage=cov)


@router.post("/systems/{sid}")
def system_update(sid: int, session: Session = Depends(db), user: AppUser = Depends(admin_user),
                  name: str = Form(...), description: str = Form(""), vendor: str = Form(""),
                  org_role: str = Form(...), risk_class: str = Form(...), generative: str = Form(""),
                  affected_persons: str = Form(""), risk_class_confirmed: str = Form("")):
    system = get_or_404(session, AISystem, sid)
    inventory.update_system(session, system, actor(user), name=name.strip(), description=description.strip(),
                            vendor=vendor.strip(), org_role=org_role, risk_class=risk_class,
                            generative=generative == "yes", affected_persons=_affected(affected_persons),
                            risk_class_confirmed=risk_class_confirmed == "yes")
    session.commit()
    return redirect(f"/systems/{sid}")


# Content -------------------------------------------------------------------

@router.get("/content")
def content_list(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    return render(request, "content_list.html", user=user, modules=content.all_modules(session))


@router.get("/content/{key}")
def content_detail(request: Request, key: str, session: Session = Depends(db), user: AppUser = Depends(current_user),
                   v: int | None = None, edit: int = 0):
    module = content.get_module(session, key)
    if module is None:
        raise HTTPException(404)
    version = next((x for x in module.versions if x.version == v), module.current) if v else module.current
    return render(request, "content_detail.html", user=user, module=module, version=version, edit=bool(edit),
                  quiz_yaml=yaml.safe_dump(module.current.quiz, sort_keys=False, allow_unicode=True), error=None)


@router.post("/content/{key}")
def content_publish(request: Request, key: str, session: Session = Depends(db), user: AppUser = Depends(admin_user),
                    title: str = Form(...), body: str = Form(...), quiz_yaml: str = Form(""),
                    material_change: str = Form(""), change_note: str = Form(...)):
    module = content.get_module(session, key)
    if module is None:
        raise HTTPException(404)
    try:
        quiz = yaml.safe_load(quiz_yaml) or []
        if not isinstance(quiz, list):
            raise ValueError("quiz must be a YAML list")
        content.publish_version(session, module, title=title.strip(), body=body.replace("\r\n", "\n"), quiz=quiz,
                                material_change=material_change == "yes", change_note=change_note.strip(),
                                actor=actor(user))
    except (ValueError, yaml.YAMLError) as exc:
        session.rollback()
        return render(request, "content_detail.html", 400, user=user, module=module, version=module.current,
                      edit=True, quiz_yaml=quiz_yaml, error=str(exc))
    session.commit()
    return redirect(f"/content/{key}")


# Learner (personal link, no account) ---------------------------------------

def _learner(session: Session, token: str) -> Person:
    person = session.scalars(select(Person).where(Person.learn_token == token, Person.active.is_(True))).first()
    if person is None:
        raise HTTPException(404)
    return person


@router.get("/learn/{token}")
def learn_home(request: Request, token: str, session: Session = Depends(db)):
    person = _learner(session, token)
    org = get_org(session)
    path = build_learning_path(person, sme_mode=org.sme_mode)
    modules = {m.key: m for m in content.all_modules(session)}
    today = utcnow().date()
    items = [(i, modules.get(i.module_key), refresh.module_status(session, person, i.module_key, today),
              refresh.latest_requirement(person, i.module_key)) for i in path.items]
    return render(request, "learn_home.html", user=None, person=person, path=path, items=items, token=token, org=org)


@router.get("/learn/{token}/{key}")
def learn_module(request: Request, token: str, key: str, session: Session = Depends(db)):
    person = _learner(session, token)
    module = content.get_module(session, key)
    if module is None:
        raise HTTPException(404)
    req = refresh.latest_requirement(person, key)
    return render(request, "learn_module.html", user=None, person=person, module=module, version=module.current,
                  token=token, req=req, results=None)


@router.post("/learn/{token}/{key}/quiz")
async def learn_quiz(request: Request, token: str, key: str, session: Session = Depends(db)):
    person = _learner(session, token)
    module = content.get_module(session, key)
    if module is None:
        raise HTTPException(404)
    form = dict(await request.form())
    results = content.score_quiz(module.current.quiz, form)
    session.add(QuizAttempt(person_id=person.id, module_key=key, content_version=module.current.version,
                            answers=form, correct=sum(r["correct"] for r in results), total=len(results)))
    # The register records that a check was taken, not the score: it is not a pass/fail measure.
    evidence.record(session, "knowledge_check_taken", f"Knowledge check for {key} taken by {person.name}",
                    person.name, person=person, module_key=key, content_version=module.current.version)
    session.commit()
    req = refresh.latest_requirement(person, key)
    return render(request, "learn_module.html", user=None, person=person, module=module, version=module.current,
                  token=token, req=req, results=results)


@router.post("/learn/{token}/{key}/complete")
def learn_complete(token: str, key: str, session: Session = Depends(db), confirm: str = Form("")):
    person = _learner(session, token)
    module = content.get_module(session, key)
    req = refresh.latest_requirement(person, key)
    if module is None or req is None:
        raise HTTPException(404)
    if confirm == "yes" and req.completed_at is None:
        refresh.complete_requirement(session, req, module.current.version, person.name)
        session.commit()
    return redirect(f"/learn/{token}")


# Evidence register ---------------------------------------------------------

def _evidence_query(measure_type: str, person_id: int | None, date_from: date | None, date_to: date | None):
    q = select(EvidenceEntry).order_by(EvidenceEntry.seq)
    if measure_type:
        q = q.where(EvidenceEntry.measure_type == measure_type)
    if person_id:
        q = q.where(EvidenceEntry.person_id == person_id)
    if date_from:
        q = q.where(EvidenceEntry.measure_date >= date_from)
    if date_to:
        q = q.where(EvidenceEntry.measure_date <= date_to)
    return q


def _parse_date(raw: str | None) -> date | None:
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        raise HTTPException(400, "Invalid date")


@router.get("/evidence")
def evidence_list(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user),
                  type: str = "", person: int | None = None, date_from: str = "", date_to: str = ""):
    q = _evidence_query(type, person, _parse_date(date_from), _parse_date(date_to))
    entries = session.scalars(q.order_by(None).order_by(EvidenceEntry.seq.desc()).limit(500)).all()
    people = session.scalars(select(Person).order_by(Person.name)).all()
    return render(request, "evidence.html", user=user, entries=entries, chain=evidence.verify_chain(session),
                  people=people, manual=MANUAL_MEASURES, filters={"type": type, "person": person,
                  "date_from": date_from, "date_to": date_to}, query=request.url.query)


@router.post("/evidence")
def evidence_add(session: Session = Depends(db), user: AppUser = Depends(admin_user),
                 measure_type: str = Form(...), title: str = Form(...), description: str = Form(""),
                 measure_date: date = Form(...), attendees: str = Form(""), reference: str = Form(""),
                 content_version: str = Form("")):
    if measure_type not in MANUAL_MEASURES:
        raise HTTPException(400, "This measure type is recorded automatically")
    details = {}
    if attendees.strip():
        details["attendees"] = [a.strip() for a in attendees.replace("\n", ",").split(",") if a.strip()]
    if reference.strip():
        details["reference"] = reference.strip()
    if content_version.strip():
        details["document_version"] = content_version.strip()
    evidence.record(session, measure_type, title.strip(), actor(user), description=description.strip(),
                    measure_date=measure_date, details=details)
    session.commit()
    return redirect("/evidence")


@router.get("/evidence.csv")
def evidence_csv(session: Session = Depends(db), user: AppUser = Depends(current_user), type: str = "",
                 person: int | None = None, date_from: str = "", date_to: str = ""):
    entries = session.scalars(_evidence_query(type, person, _parse_date(date_from), _parse_date(date_to))).all()
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    return Response(evidence.export_csv(entries), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="ai-literacy-evidence-{stamp}.csv"'})


@router.get("/evidence.pdf")
def evidence_pdf(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user),
                 type: str = "", person: int | None = None, date_from: str = "", date_to: str = ""):
    entries = session.scalars(_evidence_query(type, person, _parse_date(date_from), _parse_date(date_to))).all()
    pdf = documents.render_evidence_pdf(entries, get_org(session).org_name, evidence.verify_chain(session),
                                        request.url.query)
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="ai-literacy-evidence-{stamp}.pdf"'})


# Documents -----------------------------------------------------------------

@router.get("/documents")
def documents_list(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    docs = session.scalars(select(IssuedDocument).order_by(IssuedDocument.issued_at.desc())).all()
    return render(request, "documents.html", user=user, docs=docs)


@router.post("/documents/statement")
def documents_statement(session: Session = Depends(db), user: AppUser = Depends(current_user),
                        period_start: str = Form("")):
    doc = documents.issue_measures_statement(session, actor(user), _parse_date(period_start))
    session.commit()
    return redirect(f"/documents/{doc.doc_id}.pdf")


@router.get("/documents/{doc_id}.pdf")
def document_pdf(request: Request, doc_id: str, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    doc = documents.find(session, doc_id)
    if doc is None:
        raise HTTPException(404)
    pdf = documents.render_pdf(doc, request.app.state.settings.base_url)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{doc.doc_id}.pdf"'})


@router.get("/verify/{doc_id}")
def verify(request: Request, doc_id: str, session: Session = Depends(db)):
    doc = documents.find(session, doc_id.upper())
    result = documents.verify(session, doc) if doc else None
    return render(request, "verify.html", 200 if doc else 404, user=None, doc=doc, result=result, doc_id=doc_id,
                  disclaimer=documents.NOT_A_CERTIFICATE)


# Settings, refresh, SME ----------------------------------------------------

@router.get("/settings")
def settings_form(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    users = session.scalars(select(AppUser).order_by(AppUser.name)).all()
    reminders = session.scalars(select(Reminder).order_by(Reminder.created_at.desc()).limit(50)).all()
    return render(request, "settings.html", user=user, org=get_org(session), users=users, reminders=reminders,
                  people={p.id: p for p in session.scalars(select(Person))}, stats=None)


@router.post("/settings")
def settings_save(session: Session = Depends(db), user: AppUser = Depends(admin_user), org_name: str = Form(...),
                  refresh_interval_months: int = Form(...), reminder_lead_days: int = Form(...),
                  sme_mode: str = Form("")):
    if not 1 <= refresh_interval_months <= 60 or not 0 <= reminder_lead_days <= 180:
        raise HTTPException(400, "Out of range")
    org = get_org(session)
    new = {"org_name": org_name.strip(), "refresh_interval_months": refresh_interval_months,
           "reminder_lead_days": reminder_lead_days, "sme_mode": sme_mode == "yes"}
    changes = {k: v for k, v in new.items() if getattr(org, k) != v}
    if changes:
        for k, v in changes.items():
            setattr(org, k, v)
        evidence.record(session, "settings_changed", "AI literacy programme settings changed", actor(user),
                        details=changes)
        if "sme_mode" in changes:
            for person in session.scalars(select(Person).where(Person.active.is_(True))):
                refresh.sync_requirements(session, person, actor(user))
    session.commit()
    return redirect("/settings")


@router.post("/refresh/run")
def refresh_run(request: Request, session: Session = Depends(db), user: AppUser = Depends(admin_user)):
    stats = refresh.run_refresh_cycle(session, actor(user))
    session.commit()
    users = session.scalars(select(AppUser).order_by(AppUser.name)).all()
    reminders = session.scalars(select(Reminder).order_by(Reminder.created_at.desc()).limit(50)).all()
    return render(request, "settings.html", user=user, org=get_org(session), users=users, reminders=reminders,
                  people={p.id: p for p in session.scalars(select(Person))}, stats=stats)


@router.post("/users")
def users_add(request: Request, session: Session = Depends(db), user: AppUser = Depends(admin_user),
              name: str = Form(...), email: str = Form(...), role: str = Form(...), password: str = Form(...)):
    if role not in ("admin", "reviewer") or len(password) < 10:
        raise HTTPException(400, "Invalid role or password shorter than 10 characters")
    session.add(AppUser(name=name.strip(), email=email.strip().lower(), role=role, password_hash=hash_password(password)))
    evidence.record(session, "settings_changed", f"App {role} account created for {name.strip()}", actor(user),
                    details={"email": email.strip().lower(), "role": role, "onboarding_required": True})
    session.commit()
    return redirect("/settings")


@router.get("/sme")
def sme(request: Request, session: Session = Depends(db), user: AppUser = Depends(current_user)):
    templates = content.list_templates(request.app.state.settings.content_dir)
    return render(request, "sme.html", user=user, org=get_org(session), templates=templates)


@router.get("/sme/templates/{name}")
def sme_template(request: Request, name: str, user: AppUser = Depends(current_user), raw: int = 0):
    paths = {p.stem: p for p in content.list_templates(request.app.state.settings.content_dir)}
    if name not in paths:
        raise HTTPException(404)
    text = paths[name].read_text(encoding="utf-8")
    if raw:
        return Response(text, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
    return render(request, "sme_template.html", user=user, name=name, text=text)
