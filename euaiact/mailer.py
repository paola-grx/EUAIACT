"""E-mail delivery of queued refresh reminders (the `reminders` outbox).

run_refresh_cycle() queues reminders; deliver_reminders() sends them.
Failures are kept with the error and retried on the next run, up to
MAX_ATTEMPTS. Reminders whose training was completed in the meantime are
cancelled instead of sent.
"""

import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .content import get_module
from .db import get_org
from .inventory import ensure_learn_link
from .models import Reminder, utcnow
from .settings import SmtpSettings

MAX_ATTEMPTS = 5


class Sender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class SmtpSender:
    def __init__(self, cfg: SmtpSettings, timeout: float = 30):
        self.cfg = cfg
        self.timeout = timeout

    def send(self, message: EmailMessage) -> None:
        cfg = self.cfg
        context = ssl.create_default_context()
        if cfg.security == "ssl":
            smtp = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=self.timeout, context=context)
        else:
            smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=self.timeout)
        with smtp:
            if cfg.security == "starttls":
                smtp.starttls(context=context)
            if cfg.username:
                smtp.login(cfg.username, cfg.password)
            smtp.send_message(message)


@dataclass
class DeliveryReport:
    sent: int = 0
    failed: int = 0
    skipped_no_email: int = 0
    cancelled: int = 0
    errors: list[str] = field(default_factory=list)


def build_message(reminder: Reminder, module: str, org_name: str, sender: str, base_url: str) -> EmailMessage:
    person, req = reminder.person, reminder.requirement
    link = f"{base_url}/learn/{person.learn_token}"
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = person.email
    if reminder.kind == "overdue":
        msg["Subject"] = f"Overdue: AI training '{module}'"
        lead = f"your AI training module '{module}' was due on {req.due_on:%d %B %Y}."
    else:
        msg["Subject"] = f"Reminder: AI training '{module}' due {req.due_on:%d %B %Y}"
        lead = f"your AI training module '{module}' is due on {req.due_on:%d %B %Y}."
    msg.set_content(
        f"Hello {person.name},\n\n"
        f"{lead}\n\n"
        f"Why you have it: {req.reason}\n\n"
        f"Open your personal learning path (do not forward this link, it is personal to you):\n{link}\n\n"
        f"{org_name} runs this programme to support AI literacy under Article 4 of the EU AI Act. "
        f"The knowledge checks are for learning only; there is no pass mark.\n\n"
        f"Questions? Contact your AI literacy coordinator.\n"
    )
    return msg


def deliver_reminders(session: Session, sender: Sender, from_address: str, base_url: str) -> DeliveryReport:
    report = DeliveryReport()
    org = get_org(session)
    pending = session.scalars(select(Reminder).where(
        Reminder.sent_at.is_(None), Reminder.cancelled_at.is_(None), Reminder.attempts < MAX_ATTEMPTS,
    ).order_by(Reminder.id)).all()
    for reminder in pending:
        req, person = reminder.requirement, reminder.person
        if req.completed_at is not None or req.superseded or not person.active:
            reminder.cancelled_at = utcnow()
            report.cancelled += 1
            continue
        if not person.email:
            report.skipped_no_email += 1
            continue
        # Never e-mail a link that no longer works.
        ensure_learn_link(session, person, "reminder delivery")
        reminder.attempts += 1
        try:
            module = get_module(session, req.module_key)
            title = module.title if module else req.module_key
            sender.send(build_message(reminder, title, org.org_name, from_address, base_url))
        except (smtplib.SMTPException, OSError) as exc:
            reminder.last_error = f"{type(exc).__name__}: {exc}"[:500]
            report.failed += 1
            report.errors.append(f"{person.name}: {reminder.last_error}")
        else:
            reminder.sent_at = utcnow()
            reminder.last_error = ""
            report.sent += 1
        # Commit per message so one failure or crash does not lose the state of messages already sent.
        session.commit()
    session.commit()
    return report


def learn_link_message(person, org_name: str, sender: str, base_url: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = person.email
    msg["Subject"] = f"Your AI learning path at {org_name}"
    msg.set_content(
        f"Hello {person.name},\n\n"
        f"{org_name} supports everyone who works with AI in building the knowledge to use it well "
        f"(Article 4 of the EU AI Act). Your learning path is tailored to your role and the AI systems you use:\n\n"
        f"{base_url}/learn/{person.learn_token}\n\n"
        f"This link is personal to you: please do not forward it. Knowledge checks are for learning only; "
        f"there is no pass mark.\n"
    )
    return msg
