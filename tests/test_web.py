import re


def test_first_run_redirects_to_setup(client):
    r = client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/login"
    assert client.get("/login", follow_redirects=False).headers["location"] == "/setup"


def test_onboarding_required_before_use(client):
    client.post("/setup", data={"org_name": "Acme", "name": "Ada", "email": "a@x.eu", "password": "0123456789"})
    r = client.get("/people", follow_redirects=False)
    assert r.headers["location"] == "/onboarding"
    page = client.get("/onboarding").text
    assert "limits" in page.lower()
    assert client.get("/guidance/automation-limits").status_code == 200
    client.post("/onboarding/complete", data={"confirm": "yes"})
    assert client.get("/people").status_code == 200


def test_full_flow(admin, settings):
    c = admin
    c.post("/people", data={"name": "Lena Learner", "department": "HR"})
    c.post("/systems", data={"name": "CV Screener", "risk_class": "high", "org_role": "deployer",
                             "affected_persons": "job candidates"})
    c.post("/systems/1/assign", data={"person_id": 1, "role": "human_overseer"})
    c.post("/people/1/assessment", data={"technical_background": "basic", "ai_experience": "some"})
    page = c.get("/people/1").text
    assert "human oversight (Art. 14)" in page and "job candidates" in page

    token = re.search(r"/learn/([\w-]+)", page).group(1)
    # A learner scoring 0 can still complete: knowledge checks are not a gate.
    r = c.post(f"/learn/{token}/core/quiz", data={"q0": "0", "q1": "0", "q2": "1", "q3": "0"})
    assert "not a pass/fail test" in r.text
    c.post(f"/learn/{token}/core/complete", data={"confirm": "yes"})
    assert "Completed version 1" in c.get(f"/learn/{token}/core").text

    csv_text = c.get("/evidence.csv").text
    assert "knowledge_check_taken" in csv_text and "training_completed" in csv_text
    assert c.get("/evidence.pdf").content.startswith(b"%PDF")

    r = c.post("/people/1/record", follow_redirects=False)
    doc_id = r.headers["location"].split("/")[-1].removesuffix(".pdf")
    assert c.get(r.headers["location"]).content.startswith(b"%PDF")
    verify = c.get(f"/verify/{doc_id}")
    assert verify.status_code == 200 and "Genuine" in verify.text
    assert c.get("/verify/ALR-0000-0000-0000").status_code == 404

    r = c.post("/documents/statement", data={}, follow_redirects=False)
    assert "/documents/A4S-" in r.headers["location"]
    dash = c.get("/").text
    assert "CV Screener" in dash and "No internal AI usage policy" in dash


def test_reviewer_cannot_change_data(admin):
    admin.post("/users", data={"name": "Rev", "email": "rev@x.eu", "role": "reviewer", "password": "0123456789"})
    admin.post("/logout")
    admin.post("/login", data={"email": "rev@x.eu", "password": "0123456789"})
    assert admin.get("/", follow_redirects=False).headers["location"] == "/onboarding"
    admin.post("/onboarding/complete", data={"confirm": "yes"})
    assert admin.get("/evidence").status_code == 200
    assert admin.post("/people", data={"name": "X"}).status_code == 403


def test_material_onboarding_update_requires_redo(admin, settings):
    admin.post("/content/app-onboarding", data={"title": "Onboarding", "body": "# New\n", "quiz_yaml": "[]",
                                                "change_note": "new automation", "material_change": "yes"})
    assert admin.get("/", follow_redirects=False).headers["location"] == "/onboarding"


def test_content_edit_rejects_bad_quiz(admin):
    r = admin.post("/content/core", data={"title": "Core", "body": "x", "quiz_yaml": "- question: q\n  options: [a]\n  answer: 3",
                                          "change_note": "bad"})
    assert r.status_code == 400


def test_manual_measure_and_filters(admin):
    admin.post("/evidence", data={"measure_type": "awareness_session", "title": "AI lunch talk",
                                  "measure_date": "2026-09-01", "attendees": "A, B"})
    page = admin.get("/evidence?type=awareness_session").text
    assert "AI lunch talk" in page and "Attendees: A, B" in page
    r = admin.post("/evidence", data={"measure_type": "training_assigned", "title": "x", "measure_date": "2026-09-01"})
    assert r.status_code == 400


def test_sme_mode_and_templates(admin):
    admin.post("/settings", data={"org_name": "Tiny Ltd", "refresh_interval_months": 12, "reminder_lead_days": 30,
                                  "sme_mode": "yes"})
    admin.post("/people", data={"name": "Solo"})
    assert "SME essentials" in admin.get("/people/1").text
    assert "Internal AI usage policy" in admin.get("/sme/templates/ai-usage-policy").text


def test_classification_suggestion_shows_limits(admin):
    r = admin.post("/systems/classify", data={"annex_iii": "employment"})
    assert "High-risk" in r.text and "Art. 6(3)" in r.text


def test_legal_dates_page(admin):
    page = admin.get("/legal-dates").text
    assert "2 Dec 2027" in page.replace("02 Dec", "2 Dec") and "to verify" in page


def test_all_pages_render(admin):
    admin.post("/people", data={"name": "P"})
    admin.post("/systems", data={"name": "S", "risk_class": "limited", "generative": "yes"})
    admin.post("/systems/1/assign", data={"person_id": 1, "role": "operator"})
    admin.post("/refresh/run")
    token = re.search(r"/learn/([\w-]+)", admin.get("/people/1").text).group(1)
    for url in ["/", "/people", "/people/1", "/systems", "/systems/1", "/content", "/content/core",
                "/content/core?edit=1", "/content/core?v=1", "/evidence", "/documents", "/settings", "/sme",
                "/sme/templates/sme-minimum-viable-programme", "/legal-dates", "/onboarding",
                "/guidance/automation-limits", f"/learn/{token}", f"/learn/{token}/role-genai-user"]:
        r = admin.get(url)
        assert r.status_code == 200, url
