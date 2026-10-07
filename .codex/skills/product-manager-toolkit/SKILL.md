---
name: product-manager-toolkit
description: Plan and prioritize AI_OFFICE product work, write PRDs and acceptance criteria, analyze owner workflows, synthesize research, and maintain an evidence-based roadmap.
license: MIT
metadata:
  upstream_repo: alirezarezvani/claude-skills
  upstream_commit: 19392f7a08264ed00486a251f5b2098321771f94
  adaptation: codex-project
---

# Product Manager for AI_OFFICE

Anchor product work in the pilot's documented scope and observable owner value.
Read `README.md`, `IMPLEMENTATION_PLAN.md`, `docs/ACCEPTANCE.md`,
`docs/DELIVERY.md`, and `docs/INTEGRATION_STATUS.md` as relevant.

## Workflow

1. Frame the user problem, target user, evidence, desired outcome, and constraints.
2. Separate current behavior, requested behavior, assumptions, and open questions.
3. Define measurable success and guardrail metrics before proposing a feature.
4. Prioritize against safety, compliance, reliability, dependencies, and effort;
   do not let a numerical score hide a hard regulatory or security prerequisite.
5. Write acceptance criteria that cover success, degraded operation, denial,
   recovery, auditability, and manual fallback.
6. After delivery, compare observed results with the stated outcome and record
   follow-up work.

## Evidence rules

- Do not fabricate interviews, demand, conversion, or user preferences.
- Label synthetic examples and unvalidated assumptions.
- Keep real payments, production 1C writes, and unsupervised high-impact actions
  out of scope unless the governing product and safety requirements are revised.
- Regulatory and legal claims require the appropriate specialist review.

Use the RICE and interview scripts only with user-provided or clearly synthetic
data. The PRD assets and framework references are optional templates; adapt them
to this repository rather than creating parallel planning systems.
