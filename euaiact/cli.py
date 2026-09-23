"""Command line: python -m euaiact.cli <command>."""

import argparse
import os
import sys

from .db import init_db, make_engine, make_sessionmaker
from .legal_dates import load_milestones, unverified
from .settings import ConfigError, load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="euaiact")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)),
                       help="default: $PORT if set (hosting platforms), else 8000")
    serve.add_argument("--proxy", action="store_true",
                       help="behind a TLS-terminating reverse proxy: trust X-Forwarded-* from --forwarded-allow-ips")
    serve.add_argument("--forwarded-allow-ips", default="127.0.0.1")
    sub.add_parser("refresh", help="run the refresh cycle and e-mail reminders (schedule daily)")
    sub.add_parser("send-reminders", help="e-mail queued reminders (needs EUAIACT_SMTP_*)")
    check = sub.add_parser("check-legal-dates", help="list legal dates that still need verification")
    check.add_argument("--strict", action="store_true", help="exit 1 if any date is unverified (release gate)")
    imp = sub.add_parser("import-content", help="import changed content/modules/*.md as new versions")
    imp.add_argument("--material", action="store_true", help="mark the changes as material (triggers re-training)")
    user = sub.add_parser("create-user", help="create an app admin or reviewer")
    user.add_argument("email")
    user.add_argument("name")
    user.add_argument("--role", choices=["admin", "reviewer"], default="admin")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.cmd == "serve":
        import uvicorn

        from .web.app import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port, proxy_headers=args.proxy,
                    forwarded_allow_ips=args.forwarded_allow_ips if args.proxy else None)
        return 0

    if args.cmd == "check-legal-dates":
        milestones = load_milestones(settings.legal_dates_file)
        pending = unverified(milestones)
        for m in milestones:
            mark = "ok      " if m not in pending else "VERIFY  "
            print(f"{mark}{m.applies_from.isoformat()}  {m.label}")
        if pending:
            print(f"\n{len(pending)} of {len(milestones)} legal dates are not verified "
                  f"(set verified/verified_by/verified_on in {settings.legal_dates_file}).")
        return 1 if pending and args.strict else 0

    engine = make_engine(settings.database_url)
    init_db(engine)
    Session = make_sessionmaker(engine)
    with Session() as session:
        if args.cmd == "refresh":
            from .refresh import run_refresh_cycle

            stats = run_refresh_cycle(session, actor="scheduler")
            session.commit()
            print(stats)
            if settings.smtp is None:
                print("E-mail not configured (EUAIACT_SMTP_HOST): reminders stay queued.")
            else:
                return _send(session, settings)
        elif args.cmd == "send-reminders":
            if settings.smtp is None:
                print("E-mail not configured: set EUAIACT_SMTP_HOST and EUAIACT_SMTP_FROM.", file=sys.stderr)
                return 1
            return _send(session, settings)
        elif args.cmd == "import-content":
            from .content import sync_from_disk

            changed = sync_from_disk(session, settings.content_dir, actor="content import", material=args.material)
            print("changed:", ", ".join(changed) or "nothing")
        elif args.cmd == "create-user":
            import getpass

            from .auth import hash_password
            from .models import AppUser

            password = getpass.getpass("Password (min. 10 characters): ")
            if len(password) < 10:
                print("Password too short", file=sys.stderr)
                return 1
            session.add(AppUser(email=args.email.lower(), name=args.name, role=args.role,
                                password_hash=hash_password(password)))
            print(f"Created {args.role} {args.email}; they must complete the app onboarding at first login.")
        session.commit()
    return 0


def _send(session, settings) -> int:
    from .mailer import SmtpSender, deliver_reminders

    report = deliver_reminders(session, SmtpSender(settings.smtp), settings.smtp.sender, settings.base_url)
    print(f"e-mail: {report.sent} sent, {report.failed} failed, {report.skipped_no_email} without address, "
          f"{report.cancelled} cancelled")
    for error in report.errors:
        print("  ", error, file=sys.stderr)
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
