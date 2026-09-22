"""Command line: python -m euaiact.cli <command>."""

import argparse
import sys

from .db import init_db, make_engine, make_sessionmaker
from .legal_dates import load_milestones, unverified
from .settings import load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="euaiact")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("refresh", help="run the refresh cycle (schedule daily)")
    check = sub.add_parser("check-legal-dates", help="list legal dates that still need verification")
    check.add_argument("--strict", action="store_true", help="exit 1 if any date is unverified (release gate)")
    imp = sub.add_parser("import-content", help="import changed content/modules/*.md as new versions")
    imp.add_argument("--material", action="store_true", help="mark the changes as material (triggers re-training)")
    user = sub.add_parser("create-user", help="create an app admin or reviewer")
    user.add_argument("email")
    user.add_argument("name")
    user.add_argument("--role", choices=["admin", "reviewer"], default="admin")
    args = parser.parse_args(argv)
    settings = load_settings()

    if args.cmd == "serve":
        import uvicorn

        from .web.app import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)
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
            print(stats)
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


if __name__ == "__main__":
    sys.exit(main())
