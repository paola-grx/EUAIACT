from datetime import timedelta

from euaiact import assessment as a
from euaiact import content, inventory, refresh
from euaiact.models import Reminder


def complete_all(session, person):
    for r in list(person.requirements):
        if r.completed_at is None and not r.superseded:
            refresh.complete_requirement(session, r, content.get_module(session, r.module_key).current.version, "t")


def open_keys(person):
    return sorted((r.module_key, r.trigger) for r in person.requirements if r.completed_at is None and not r.superseded)


def test_initial_requirements_created(session):
    p = inventory.add_person(session, "t", name="A")
    assert open_keys(p) == [(a.CORE, "initial")]


def test_new_system_triggers_retraining(session):
    p = inventory.add_person(session, "t", name="A")
    complete_all(session, p)
    bot = inventory.add_system(session, "t", name="Chatbot", risk_class="minimal")
    inventory.assign(session, p, bot, "casual_user", "t")
    # No role-specific module for a general chatbot: core is re-visited.
    assert open_keys(p) == [(a.CORE, "new_system")]


def test_role_change_triggers_role_modules(session):
    p = inventory.add_person(session, "t", name="A")
    s = inventory.add_system(session, "t", name="HR tool", risk_class="high", org_role="deployer")
    inventory.assign(session, p, s, "operator", "t")
    complete_all(session, p)
    inventory.assign(session, p, s, "human_overseer", "t")
    assert (a.OVERSEER, "initial") in open_keys(p)
    assert (a.DEPLOYER_HR, "role_change") in open_keys(p)


def test_material_content_update_retrains_only_completers(session):
    done = inventory.add_person(session, "t", name="Done")
    pending = inventory.add_person(session, "t", name="Pending")
    complete_all(session, done)
    core = content.get_module(session, a.CORE)
    content.publish_version(session, core, title=core.title, body=core.current.body_markdown + "\nTypo fix\n",
                            quiz=core.current.quiz, material_change=False, change_note="typo", actor="t")
    assert open_keys(done) == []
    content.publish_version(session, core, title=core.title, body=core.current.body_markdown + "\nNew rule\n",
                            quiz=core.current.quiz, material_change=True, change_note="new policy", actor="t")
    assert open_keys(done) == [(a.CORE, "content_update")]
    assert open_keys(pending) == [(a.CORE, "initial")]


def test_periodic_refresh_and_reminders_are_idempotent(session):
    p = inventory.add_person(session, "t", name="A")
    complete_all(session, p)
    today = refresh._today()
    assert refresh.run_refresh_cycle(session, today=today) == {"periodic_created": 0, "reminders_queued": 0}
    later = refresh.add_months(today, 12) - timedelta(days=10)  # inside the 30-day lead time
    stats = refresh.run_refresh_cycle(session, today=later)
    assert stats == {"periodic_created": 1, "reminders_queued": 1}
    assert refresh.run_refresh_cycle(session, today=later) == {"periodic_created": 0, "reminders_queued": 0}
    overdue_day = refresh.add_months(today, 12) + timedelta(days=1)
    assert refresh.run_refresh_cycle(session, today=overdue_day)["reminders_queued"] == 1
    assert {r.kind for r in session.query(Reminder)} == {"due_soon", "overdue"}


def test_configurable_interval(session):
    from euaiact.db import get_org

    get_org(session).refresh_interval_months = 6
    p = inventory.add_person(session, "t", name="A")
    complete_all(session, p)
    req = refresh.latest_requirement(p, a.CORE)
    assert refresh.completion_expires(session, req) == refresh.add_months(req.completed_at.date(), 6)


def test_removed_role_supersedes_open_items(session):
    p = inventory.add_person(session, "t", name="A")
    s = inventory.add_system(session, "t", name="Model", org_role="provider")
    assignment = inventory.assign(session, p, s, "developer", "t")
    assert (a.DEVELOPER, "initial") in open_keys(p)
    inventory.unassign(session, assignment, "t")
    assert a.DEVELOPER not in {k for k, _ in open_keys(p)}
