# AI_OFFICE repository guidance

## Project profile

AI_OFFICE is a local pilot for an owner's multi-agent office. The backend is
Python 3.12 with FastAPI, Pydantic, async SQLAlchemy/Alembic,
PostgreSQL/pgvector, Redis/Celery, and optional S3/MinIO. The frontend is a
React/Vite JavaScript application. Treat `README.md` and the current code as the
source of truth; older planning documents may describe incomplete work.

## Non-negotiable invariants

- Agents never execute real payments. High-impact business actions remain human
  decisions behind policy and approval gates.
- Legal analysis requires jurisdiction and effective date and preserves the
  configured ConsultantPlus source/sufficiency/citation gates.
- Scope tenant-owned data by `company_id` at every boundary.
- Preserve short-lived capability grants, least privilege, kill switches,
  autonomy ceilings, audit events, idempotency, bounded retry, and fail-closed
  provider behavior.
- Route external model traffic through data classification, DLP, and the egress
  gateway. Attachments are untrusted input.
- Never weaken tests, golden values, or security controls merely to make a change
  pass.

## Codex role skills

Project-scoped skills live in `.codex/skills/`. Use `ai-office-team` for broad
work or the narrow specialist that matches the request:

- `senior-architect`, `senior-backend`, `senior-frontend`, `senior-devops`
- `senior-qa`, `rag-architect`, `senior-security`
- `product-manager-toolkit`, `financial-analyst`, `general-counsel-advisor`

Load only the needed skill and references. These roles guide Codex while working
on the repository; they are not automatically part of the application's runtime
agent graph. See `docs/CODEX_SKILLS.md` for provenance and runtime integration.

## Engineering conventions

- Follow existing modules and type contracts. Prefer focused changes over new
  frameworks or parallel abstractions.
- Backend code must pass strict typing and use migrations for schema changes.
- Frontend changes reuse `src/api/client.js`, feature modules, and design tokens.
- Update documentation and generated OpenAPI/types when their source contracts
  change.
- Inspect bundled skill scripts before running them. Use scratch directories for
  generators. Load tests, Terraform, deployment, remote scanning, and any
  non-local target require explicit authorization.

## Verification

Run the smallest relevant checks first. For a full local quality pass:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
Push-Location frontend
npm test
npm run build
Pop-Location
```

Use the opt-in PostgreSQL, MinIO, semantic-model, or Docker smoke workflows when
the change depends on them. Report unavailable infrastructure and skipped checks
explicitly.
