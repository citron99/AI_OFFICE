---
name: senior-qa
description: Design, add, run, or review tests for AI_OFFICE across pytest unit/integration/PostgreSQL/e2e/eval suites and the React/Vite node:test frontend suite.
license: MIT
metadata:
  upstream_repo: alirezarezvani/claude-skills
  upstream_commit: 19392f7a08264ed00486a251f5b2098321771f94
  adaptation: codex-project
---

# Senior QA Engineer for AI_OFFICE

Test observable contracts and risk controls, not implementation trivia.

## Workflow

1. Identify the affected invariant and the cheapest test layer that can prove it.
2. Add a regression test that fails for the original defect or missing behavior.
3. Cover important negative paths: cross-company access, expired grants,
   concurrent updates, missing legal sources, DLP blocks, provider failure,
   approval invalidation, and retry/checkpoint recovery.
4. Use PostgreSQL tests for database semantics that SQLite cannot represent.
5. Keep external-model and infrastructure tests opt-in and deterministic where
   possible. Report skips and environmental gaps separately from passes.
6. Run the focused test, then the applicable quality gates in `AGENTS.md`.

## Quality rules

- Do not weaken assertions, delete scenarios, or rewrite golden values merely to
  make a failing implementation pass.
- Prefer public behavior and stable fixtures; eliminate time, ordering, and
  network flakiness.
- Security and finance calculations need boundary-value tests.
- Legal outputs need source, jurisdiction, effective-date, and citation checks.
- Frontend tests must include denied/waiting/error states, not only success.

The bundled generators target Jest/Next.js and are not the project default.
Consult `references/testing_strategies.md`,
`references/test_automation_patterns.md`, or
`references/qa_best_practices.md` as needed; use generation scripts only in scratch space
and adapt the result to pytest or `node:test` before committing it.
