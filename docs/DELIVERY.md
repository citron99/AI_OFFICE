# Карта поставки MVP (ТЗ V2.1 раздел 15.1, D-01..D-11)

| ID | Артефакт | Где в репозитории |
| --- | --- | --- |
| D-01 | Исходный код backend/frontend и reproducible dependency locks | `app/`, `frontend/`, `uv.lock`, `frontend/package-lock.json` |
| D-02 | Docker Compose, Dockerfiles, migrations и seed demo data | `docker-compose.yml` (MinIO — профиль `s3`), `Dockerfile*`, `migrations/` (0001→0019), синтетический датасет `app/accounting/mock.py` |
| D-03 | OpenAPI, JSON/Pydantic schemas и provider contracts | `docs/openapi.json` (перегенерация: `uv run python scripts/export_openapi.py`), `app/accounting/provider.py`, `app/integrations/consultant_plus/provider.py`, `app/llm/base.py` |
| D-04 | Версионированные ProcessDefinition, prompts и policies | `processes/*.v3.json`, `app/orchestrator/passport.py`, `app/prompts/legal.py`, `app/core/policy.py` (`POLICY_VERSION`) |
| D-05 | Mock1CConnector и production-ready AccountingProvider adapter skeleton | `app/accounting/mock.py` (полный контракт ТЗ 8.2), `app/accounting/provider.py`, `app/accounting/factory.py` |
| D-06 | ConsultantPlusProvider contract/adapter и Legal RAG ingestion/retrieval с source registry | `app/integrations/consultant_plus/`, `app/services/knowledge.py`, `app/agents/lawyer.py` |
| D-07 | Eval dataset, automated tests и отчёт | `tests/evals/` (84 сценария), `scripts/run_evals.py`, `tests/unit/golden_values.json` (ACC-01) |
| D-08 | Security model, data flow map, RBAC matrix и threat model | `docs/SECURITY_MODEL.md` |
| D-09 | Runbooks: deployment, backup/restore, provider outage, incident, kill switch, manual mode | `docs/RUNBOOKS.md` |
| D-10 | User guide для собственника | `docs/STATUS.md`, README (краткий старт); обучающая сессия — вне репозитория |
| D-11 | Pilot report: baseline, метрики, решение stop/change/expand | Шаблон метрик — `app/api/v1/reviews.py` (`/processes/quality`, `/processes/controls`); заполняется по итогам 30-дневного пилота (ТЗ 14) |

## Проверка поставки

```bash
uv sync --locked
uv run ruff check . && uv run ruff format --check . && uv run mypy app
uv run pytest -q                                   # 384+ теста, включая eval-набор
uv run python scripts/run_evals.py                 # закрытый набор: отчёт
TEST_POSTGRES_URL=... uv run pytest tests/postgres -q   # реальные конкурентные тесты
TEST_S3_URL=... uv run pytest tests/integration/test_object_storage.py -q  # MinIO
docker compose up -d --build && curl -fsS localhost:8000/ready
```
