# Acceptance baseline — local AI-office pilot

## Delivered scope

- React workspace with owner-scoped tasks, accounting view, approvals, knowledge
  sources, process graph, result review, and control metrics.
- FastAPI, PostgreSQL/pgvector, Redis, Celery worker and dispatcher run through
  Docker Compose; health is available at `GET /ready`.
- The payment route creates only a synthetic draft after an owner approval. The
  code has no real payment or accounting-write capability.
- Accounting is deterministic, RUB-denominated synthetic data behind a provider
  interface. A real 1C connector is intentionally not enabled.
- The task graph persists accountant, security preflight, lawyer, and security
  postflight nodes. Policy runs only after postflight.
- Postflight evaluates safe structured controls, records bank-detail and
  counterparty flags, and does not retain document text or requisites.
- `GET /api/v1/processes/controls` exposes owner-scoped aggregate coverage,
  policy decisions, and control flags without exposing task contents.

## Acceptance evidence

- Unit tests: `121 passed` on the current local checkout.
- Targeted office/process tests and static checks pass (`ruff`, `mypy`).
- Frontend tests and production Vite build pass.
- Docker smoke verifies queue dispatch, four-step office execution, postflight,
  idempotency, approval, one mock draft, cancellation, policy denial, and the
  financial report through the frontend proxy.

## Required deployment checks

```powershell
docker compose up -d --build
uv run python scripts/smoke_office.py --url http://127.0.0.1:8080
```

For CI, the workflow additionally tests PostgreSQL migrations, concurrency, the
offline retrieval gate, and the Compose smoke.

## Deliberate non-production boundaries

This is a completed local pilot, not authorization for real money movement,
real 1C writes, or production legal advice. Enabling any of those requires a
separate security review, connector contract, access controls, monitoring, data
retention policy, and business-owner approval.
