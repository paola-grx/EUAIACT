# EUAIACT: Article 4 AI Literacy Module

Tooling that helps providers and deployers document the measures they take under
**Article 4 of Regulation (EU) 2024/1689 (AI Act)**, as amended by
**Regulation (EU) 2026/1744 (Digital Omnibus, in force 27 July 2026)**.

> Article 4 requires *measures to support* the AI literacy of staff and others operating
> AI systems on the organisation's behalf, taking into account their technical knowledge,
> experience, education, training, the context of use and the persons affected. No specific
> individual level has to be guaranteed. It applies to every provider and deployer,
> whatever the risk class, including general chatbots and copilots.

This app documents measures. It does **not** certify competence or legal compliance, and
it is not legal advice.

## Features

| # | Feature | Where |
|---|---|---|
| 1 | AI system and role inventory: people linked to the systems they use, develop or oversee, with a role (developer, operator, decision-maker, human overseer, casual user) | `inventory.py`, `/people`, `/systems` |
| 2 | Contextual needs assessment and a **tailored learning path**, with the reason for every module shown | `assessment.py` |
| 3 | Training content as editable, **versioned Markdown**: core, primer, role modules (developers, human overseers, Art. 26 deployers, Art. 50 generative AI) and awareness of affected persons | `content/modules/*.md`, `/content` |
| 4 | Knowledge checks for **reinforcement only**. There is no pass mark, and scores never reach the evidence register | `/learn/<token>` |
| 5 | **Evidence register**: timestamped, append-only, SHA-256 hash-chained, exportable as CSV/PDF for market surveillance authorities | `evidence.py`, `/evidence` |
| 6 | Refresh cycle (default 12 months, configurable) with reminders, plus automatic re-training on a new AI system, a role change or a material content update | `refresh.py` |
| 7 | Organisation dashboard: staff coverage %, coverage per system, overdue items, gaps | `dashboard.py`, `/` |
| 8 | **AI Literacy Training Record** (individual) and **Article 4 Measures Statement** (organisation): PDFs with a unique ID and QR verification (`/verify/<id>`) | `documents.py` |
| 9 | SME mode: minimum viable programme plus templates (AI usage policy, MVP checklist, awareness session record) | `/sme`, `content/templates/` |

**The app meets Article 4 itself.** Admins and reviewers must complete an app onboarding
(`content/modules/app-onboarding.md`) before using the app, and again after each material
update to it. In-app guidance (`/guidance/automation-limits`) explains the limits of the
automated risk class suggestion, the learning path rules and the coverage figures. A
suggested risk class stays "unconfirmed" until a person confirms it.

## Quick start

```bash
pip install -e ".[dev]"
python -m euaiact.cli serve            # http://127.0.0.1:8000; first visit creates the admin
pytest -q
```

Environment variables: `EUAIACT_DATABASE_URL` (default `sqlite:///var/euaiact.db`),
`EUAIACT_SECRET_KEY` (**set in production**), `EUAIACT_BASE_URL` (used in QR codes and
learning links), `EUAIACT_CONTENT_DIR`, `EUAIACT_LEGAL_DATES`.

### CLI

```bash
python -m euaiact.cli refresh                      # run daily (cron): refresh assignments + reminders
python -m euaiact.cli import-content [--material]  # publish edited content/modules/*.md as new versions
python -m euaiact.cli create-user EMAIL NAME --role admin|reviewer
python -m euaiact.cli check-legal-dates --strict   # release gate: exit 1 while dates are unverified
```

## Legal dates: verify before release

`config/legal_dates.yaml` holds the application dates. Every entry ships with
`verified: false`, and the app shows a banner until each one has been checked against the
Official Journal:

| Milestone | Applies from |
|---|---|
| Prohibitions (Art. 5) | 2 Feb 2025 |
| New prohibitions added by the Omnibus | 2 Dec 2026 |
| AI literacy (Art. 4) | 2 Feb 2025; amended wording since 27 Jul 2026 |
| GPAI obligations | 2 Aug 2025; full enforcement 2 Aug 2026 |
| Transparency (Art. 50) | 2 Aug 2026; Art. 50(2) transition for existing systems to 2 Dec 2026 |
| High-risk, Annex III | 2 Dec 2027 |
| High-risk, Annex I | 2 Aug 2028 |

## How it works

- **Learning path rules** (`assessment.py`): the core module for everyone (or *SME
  essentials* in SME mode); the primer for foundation depth; developer module for the
  developer role; oversight module for human overseers and for decision-makers on high-risk
  systems; Art. 26 module for operators, decision-makers and overseers of high-risk systems
  the organisation deploys; Art. 50 module for generative or transparency-relevant
  systems; the affected-persons module when a system has affected groups or is high-risk.
- **Re-training triggers** (`refresh.py`): linking a person to a new system re-assigns
  the modules that system requires (or the core module, if it requires none, such as a
  general chatbot). A role change does the same. A *material* content update re-assigns the
  module to everyone who completed an earlier version. The refresh cycle re-assigns modules
  once the interval has passed.
- **Immutability**: evidence entries, issued documents and content versions are protected
  by an ORM guard and SQLite `BEFORE UPDATE/DELETE` triggers. The hash chain detects any
  tampering at database level (`verify_chain`, shown on the dashboard and in exports).
- **Staff access**: staff need no account. Each person has a personal learning link. Admins
  can also record training delivered elsewhere (classroom, external e-learning).
- **Reminders** are queued in an outbox table (`reminders`) for an e-mail or chat
  integration to deliver.
