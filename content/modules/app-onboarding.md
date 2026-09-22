---
key: app-onboarding
title: "Onboarding for admins and reviewers of this app"
audience: app
quiz:
  - question: "The app suggests a risk class of 'minimal' for a new system. What should you do?"
    options:
      - "Accept it, the classification is automated"
      - "Review it against the system's real use and confirm or change it"
    answer: 1
    explain: "The classification is a screening aid with known limits; a person must confirm it."
  - question: "A person scored 1 out of 4 in a knowledge check. What does that mean for their training record?"
    options:
      - "The training is failed and must be withheld from the record"
      - "Nothing for the record; checks are for learning reinforcement only"
    answer: 1
    explain: "Art. 4 requires measures, not a guaranteed individual level; knowledge checks are not a pass/fail gate."
  - question: "Can an evidence register entry be edited after it was recorded?"
    options:
      - "Yes, by admins"
      - "No; corrections are recorded as new entries"
    answer: 1
    explain: "The register is append-only and hash-chained so authorities can rely on it."
---

# Onboarding for admins and reviewers of this app

This app supports your organisation's Article 4 AI literacy measures. The
app itself uses automation, so the people running it need AI literacy too.
Complete this onboarding before managing the programme.

## 1. What Article 4 asks, and what it does not

- Providers and deployers **take measures to support** AI literacy of staff
  and others operating AI on their behalf.
- Measures should consider technical knowledge, experience, education,
  training, context of use and the persons affected.
- **No specific individual level must be guaranteed.** There is no
  prescribed certificate or exam.
- It applies to **every** provider and deployer, whatever the risk class,
  including general chatbots and copilots.

## 2. What the app automates, and its limits

| Automated feature | What it does | Limits |
|---|---|---|
| Risk class suggestion | Maps questionnaire answers to a class | Screening aid only; ignores Art. 6(3) exceptions and Art. 5; needs human confirmation |
| Learning path | Picks modules from role, systems and background | Rule-based; cannot see real work practices; review and adjust assignments |
| Re-training triggers | Assigns modules on new systems, role changes, material content updates, refresh cycle | Only as good as the inventory you keep up to date |
| Dashboard coverage | Counts current required modules | Measures activity, not competence |

See **Guidance > Limits of automation** in the app for details.

## 3. Your responsibilities

- Keep the AI system and role inventory current.
- Confirm or correct suggested risk classes.
- Record measures that happen outside the app (policies, awareness
  sessions, guidance) in the evidence register.
- Mark content updates as *material* only when they change what people need
  to know or do; material updates trigger re-training.
- Never describe records or statements as certificates of competence or
  compliance.

## 4. The evidence register

Every measure is logged with a timestamp in an append-only, hash-chained
register. Nothing can be edited or deleted; corrections are new entries.
Exports (CSV/PDF) are designed for market surveillance authorities.
