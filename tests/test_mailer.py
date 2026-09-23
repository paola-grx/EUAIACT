import socket
from datetime import timedelta

import pytest

from euaiact import content, inventory, mailer, refresh
from euaiact.models import Reminder
from euaiact.settings import SmtpSettings


class FakeSender:
    def __init__(self, fail_for: set[str] = frozenset()):
        self.sent = []
        self.fail_for = fail_for

    def send(self, message):
        if message["To"] in self.fail_for:
            raise mailer.smtplib.SMTPRecipientsRefused({message["To"]: (550, b"no such user")})
        self.sent.append(message)


def overdue_reminders(session, *people):
    far = refresh._today() + timedelta(days=60)  # past the 30-day initial due date
    refresh.run_refresh_cycle(session, today=far)
    session.commit()
    return session.query(Reminder).all()


def deliver(session, sender):
    return mailer.deliver_reminders(session, sender, "ai-literacy@acme.example", "https://ai.acme.example")


def test_reminders_sent_once_with_personal_link(session):
    p = inventory.add_person(session, "t", name="Ann", email="ann@acme.example")
    overdue_reminders(session)
    sender = FakeSender()
    report = deliver(session, sender)
    assert (report.sent, report.failed) == (1, 0)
    msg = sender.sent[0]
    assert msg["To"] == "ann@acme.example" and msg["Subject"].startswith("Overdue:")
    body = msg.get_content()
    assert f"https://ai.acme.example/learn/{p.learn_token}" in body
    assert "no pass mark" in body and "certif" not in body.lower()
    assert deliver(session, sender).sent == 0  # never sent twice


def test_skips_people_without_email_and_cancels_completed(session):
    inventory.add_person(session, "t", name="NoMail")
    done = inventory.add_person(session, "t", name="Done", email="done@acme.example")
    overdue_reminders(session)
    req = refresh.latest_requirement(done, "core")
    refresh.complete_requirement(session, req, content.get_module(session, "core").current.version, "t")
    report = deliver(session, FakeSender())
    assert (report.sent, report.skipped_no_email, report.cancelled) == (0, 1, 1)


def test_failures_are_recorded_and_retried(session):
    inventory.add_person(session, "t", name="Bob", email="bob@acme.example")
    overdue_reminders(session)
    report = deliver(session, FakeSender(fail_for={"bob@acme.example"}))
    assert report.failed == 1
    r = session.query(Reminder).one()
    assert r.attempts == 1 and "SMTPRecipientsRefused" in r.last_error and r.sent_at is None
    assert deliver(session, FakeSender()).sent == 1
    assert session.query(Reminder).one().last_error == ""


def test_expired_link_reissued_before_sending(session):
    p = inventory.add_person(session, "t", name="Old", email="old@acme.example")
    p.learn_token_issued_at -= timedelta(days=400)
    old = p.learn_token
    overdue_reminders(session)
    sender = FakeSender()
    deliver(session, sender)
    assert p.learn_token != old and p.learn_token in sender.sent[0].get_content()


def test_smtp_sender_against_local_server(session):
    aiosmtpd = pytest.importorskip("aiosmtpd.controller")
    from aiosmtpd.handlers import Sink

    class Collect(Sink):
        messages = []

        async def handle_DATA(self, server, smtp_session, envelope):
            self.messages.append(envelope)
            return "250 OK"

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    handler = Collect()
    controller = aiosmtpd.Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        inventory.add_person(session, "t", name="Cy", email="cy@acme.example")
        overdue_reminders(session)
        cfg = SmtpSettings(host="127.0.0.1", port=port, sender="ai@acme.example", security="none")
        report = mailer.deliver_reminders(session, mailer.SmtpSender(cfg), cfg.sender, "https://x")
        assert report.sent == 1
        assert handler.messages[0].rcpt_tos == ["cy@acme.example"]
    finally:
        controller.stop()
