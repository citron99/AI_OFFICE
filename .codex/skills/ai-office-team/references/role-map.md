# AI_OFFICE role map

Pick one lead role. Add a reviewer only when the request crosses its boundary.

| Request | Lead skill | Add when needed | Primary project evidence |
| --- | --- | --- | --- |
| Architecture, ADR, process topology, system boundary | `senior-architect` | `senior-security`, `senior-qa` | `docs/TECHNICAL_DESIGN_V2_1.md`, `docs/SECURITY_MODEL.md` |
| FastAPI, database, migrations, queue, auth, orchestration | `senior-backend` | `senior-security`, `senior-qa` | `app/`, `migrations/`, `docs/openapi.json` |
| React owner workspace and API-driven UI | `senior-frontend` | `senior-qa`, `product-manager-toolkit` | `frontend/src/`, `frontend/tests/`, `docs/design/` |
| Compose, CI, local operations, runbooks | `senior-devops` | `senior-security`, `senior-qa` | `docker-compose.yml`, `.github/workflows/`, `docs/RUNBOOKS.md` |
| Regression strategy, coverage, acceptance, evals | `senior-qa` | affected domain role | `tests/`, `docs/ACCEPTANCE.md` |
| Retrieval, chunking, pgvector, embeddings, grounding | `rag-architect` | `general-counsel-advisor`, `senior-qa` | `docs/LEGAL_RAG.md`, retrieval fixtures and tests |
| Threat model, auth, tenancy, grants, DLP, secrets | `senior-security` | affected implementation role | `docs/SECURITY_MODEL.md`, `app/security/`, auth tests |
| PRD, roadmap, prioritization, owner journey | `product-manager-toolkit` | architect, legal, finance, or security | `IMPLEMENTATION_PLAN.md`, `docs/DELIVERY.md` |
| Accounting output, budget, cash, forecast, valuation | `financial-analyst` | `senior-backend`, `senior-security` | `docs/FINANCIAL_REPORTS.md`, accounting code and golden values |
| Contract, privacy, IP, regulatory issue-spotting | `general-counsel-advisor` | `rag-architect`, `senior-security` | `docs/LEGAL_RAG.md`, cited primary sources |

For a feature spanning product, architecture, implementation, and QA, use the
sequence product scope → architecture/risk review → implementation role → QA.
Do not simulate a board meeting or load all roles for routine changes.
