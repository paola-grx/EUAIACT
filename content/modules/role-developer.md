---
key: role-developer
title: "Role module: developers and system builders"
audience: role
quiz:
  - question: "Which is the best evidence that a model performs acceptably for all user groups?"
    options:
      - "High overall accuracy on the training set"
      - "Disaggregated test results per relevant group on held-out data"
      - "Positive feedback from the product owner"
    answer: 1
    explain: "Aggregate metrics hide group-level failures; evaluate per group on data not used for training."
  - question: "Why document data sources, preprocessing and known limitations?"
    options:
      - "It is only needed for high-risk systems"
      - "So deployers, overseers and auditors understand what the system can and cannot do"
      - "It is optional good practice with no users"
    answer: 1
    explain: "Documentation lets others use and oversee the system correctly; for high-risk systems it is also mandatory (Art. 11, Annex IV)."
---

# Role module: developers and system builders

For people who build, train, fine-tune, integrate or configure AI systems,
including prompt engineering and low-code AI workflows.

## 1. Data governance

- Know where training, validation and test data come from and on what legal
  basis they are processed.
- Check data for relevance, representativeness, errors and gaps; record
  what you found and what you did about it (cf. Art. 10 for high-risk).
- Keep training, validation and test sets separate; avoid leakage.
- Minimise personal data and apply pseudonymisation where possible.

## 2. Testing and evaluation

- Define acceptance criteria before testing, tied to the intended purpose.
- Test on held-out data and on realistic edge cases.
- Report metrics **per relevant group** (bias testing), not only overall.
- Test robustness: noisy input, adversarial prompts, prompt injection,
  distribution shift.
- Re-test after every material change to model, data or prompts.

## 3. Documentation

Document at least: intended purpose and out-of-scope uses, data sources,
model and version, evaluation results and known limitations, human
oversight measures, and logging. High-risk systems need the full technical
documentation of Art. 11 and Annex IV.

## 4. Designing for oversight

Build in what overseers need (Art. 14 for high-risk): explanations or
confidence indicators, the ability to override or stop, clear logs.

## 5. Working with general-purpose models

When building on a GPAI model, read the provider's documentation and usage
policy, and pass on relevant limitations to your deployers and users.
