---
name: senior-backend
description: "Build, debug, or review the AI_OFFICE Python backend: FastAPI, Pydantic, async SQLAlchemy/Alembic, PostgreSQL/pgvector, Redis/Celery, APIs, authentication, repositories, and agent execution."
license: MIT
metadata:
  upstream_repo: alirezarezvani/claude-skills
  upstream_commit: 19392f7a08264ed00486a251f5b2098321771f94
  adaptation: codex-project
---

# Senior Backend Engineer for AI_OFFICE

Work with the existing Python 3.12 stack and repository patterns. Do not replace
the architecture with the upstream Node/Express examples.

## Workflow

1. Trace the request through API, service, orchestrator, repository, model, and
   migration layers before editing.
2. Preserve typed contracts and explicit state transitions. Check idempotency,
   concurrency, authorization, company scoping, and failure-safe behavior.
3. For schema changes, add an Alembic migration and exercise the PostgreSQL path
   when the change depends on constraints, locking, pgvector, or concurrency.
4. For API changes, update Pydantic models, tests, and `docs/openapi.json` through
   the repository's export workflow when appropriate.
5. Run focused tests first, then `ruff`, `mypy`, and the relevant integration or
   PostgreSQL tests.

## Non-negotiable checks

- Every tenant-owned query is scoped by `company_id`.
- Agent/provider access is mediated by capability grants and the data-egress
  boundary; never bypass them for convenience.
- Task and approval transitions remain deterministic and auditable.
- No real payment or irreversible business action is added to an agent path.
- Provider failures return controlled domain states rather than leaking errors
  or silently fabricating success.

## Bundled resources

Use `references/api_design_patterns.md`,
`references/database_optimization_guide.md`, and
`references/backend_security_practices.md` only when relevant. The bundled
decision engine's `fastapi-python` profile can inform a design, but the checked-in
code wins. Do not use the Express scaffolder for this project. Run the network
load tester only against an explicitly authorized local/test endpoint and with a
bounded request rate.
