# Статус интеграции: единый AI-Офис собственника

Дата: 2026-09-08. База: `AI_OFFICE_INVEST-github-merged-v2` (единственная основа backend).
Ветки: `main` — неизменённая база; `integration/backend-controls` — вся новая backend-работа;
`integration/acceptance` — свод; reference-архивы лежат отдельно и никуда не копировались.

## Что реализовано (в отличие от исходных проектов)

| Блок ТЗ V2.1 | Было в merged-v2 | Стало | Где |
| --- | --- | --- | --- |
| Policy Gate 7.2 (100k/200k) | Инвертированная логика | Матрица ALLOW_READ / ALLOW_DRAFT / REQUIRE_OWNER_APPROVAL / DENY / ESCALATE / OWNER_ONLY_OUTSIDE_AGENT, границы включительные | `app/core/policy.py` |
| APR-006 (ADMIN ≠ approver) | `role in {owner, admin}` | `require_business_owner` (только OWNER); роли owner/admin/auditor/accountant/lawyer/security | `app/api/auth.py` |
| APR-005 (payload изменён) | 409 без статуса | Статус `invalidated` + время | `app/services/approvals.py` |
| AccountingProvider 8.2 | Только коллекции | healthcheck, watermark, sync_read_only, list_*, get_counterparty_status, reconcile_snapshot, calculate_data_quality, create_draft (выключен по умолчанию) | `app/accounting/provider.py`, `app/accounting/mock.py` |
| Консультант+ (LEG-001..008) | Отсутствовал | `app/integrations/consultant_plus`: контракт, mock-лицензированный канал, licensed-скелет, режим off; поиск обязателен до Legal RAG; WAITING_SOURCE / LEGAL_SOURCE_NOT_FOUND; журнал `consultant_plus_search_events` (метаданные, без текстов) | `app/integrations/consultant_plus/`, `app/agents/lawyer.py` |
| Состояния ТЗ (TASK-003) | Нет WAITING_SOURCE/FAILED_SAFE | Полный набор + разрешённые переходы | `app/models/enums.py`, `app/orchestrator/state_machine.py` |
| Checkpoint/retry/DLQ (REL-001..009) | Retry описан, не исполнялся | Timeout + bounded retry/backoff в GraphExecutor; FAILED_SAFE; `execution_checkpoints`, `provider_calls`, `dead_letter_entries`; retry возобновляет с последнего checkpoint | `app/orchestrator/graph.py`, `app/services/tasks.py` |
| Company isolation (10.1, TASK-002, ACC-05) | Нет company_id | companies + memberships; company_id во всех доменных таблицах; проверка user→membership→company на каждый запрос в режимах token/OIDC; статические demo/API-ключи задаются сервером; идемпотентность `UNIQUE(company_id, idempotency_key)`; 404 через границу компаний | `app/db/tables/companies.py`, миграция 0015 |
| Kill switch и автономность (7.1, REL-006, ACC-10) | Нет | `process_runtime`: уровень A0..A3 + независимые переключатели процесс/LLM/write; GET/POST `/api/v1/processes/{id}/runtime` (только OWNER); процесс off → ручной режим | `app/services/contour_state.py` |
| Machine identities и grants (10.1) | Нет | Статичный реестр principals (agt_*), матрица least-privilege, capability registry на каждый узел графа; гранты с company/task/step/policy scope и TTL 15 мин пишутся в `capability_grants` и перепроверяются перед вызовом провайдера; provider_calls несут machine identity | `app/agents/principals.py`, `app/orchestrator/capabilities.py`, миграция 0017 |
| ProcessDefinitionV3 (3.2) | Только V2 | Паспорт процесса: trigger, результат, владелец, критерии приёмки, источники, stop-conditions, эскалация, manual fallback, потолок автономности, версии политики/схемы; JSON-паспорта в `processes/*.v3.json`; runtime API не может поднять уровень выше потолка паспорта | `app/orchestrator/passport.py`, `processes/` |
| Data Egress Gateway (10.2-10.3) | Нет | Детерминированный классификатор классов данных (PUBLIC..RESTRICTED), DLP-редакция секретов, шлюз перед каждым внешним LLM-вызовом: RESTRICTED/CONFIDENTIAL/PERSONAL наружу не уходят; в логах — хеш контента, не контент | `app/security/` |
| Фронтенд (12) | Упрощённый JSX | Портирован дизайн-проект: токены/темы, Navbar, KPI-карточки (watermark 1С), Top non-payment risks, ApprovalModal с payload-diff, TaskDagView, Legal view со статусом Консультант+ (эндпоинт уже есть в этом репозитории), Activity/Audit; feature-структура `src/features/*`, единый API-client `src/api/client.js`; 20/20 тестов, build 278 kB | `frontend/src/` (ветка integration/frontend-v3, смержена) |
| Жизненный цикл файлов (ART-002..006) | Частично | DLP-префильтр классификатором до записи: RESTRICTED отклоняется без сохранения; артефакты несут classification, dlp_rules, provenance и retention_until (миграция 0018); DELETE /api/v1/files/{id} каскадно удаляет источник, chunks, embeddings и файл | `app/services/files.py` |
| Планировщик (14, 8) | Отсутствовал | ScheduleConfig: IANA-таймзона владельца, время запуска, рабочий календарь, retry-cooldown, опциональный гейт свежести snapshot 1С; детерминированные решения DUE/NOT_DUE/DISABLED/NON_WORKING_DAY/SNAPSHOT_STALE/COOLDOWN; `process_schedules` (миграция 0019); GET/PUT `/processes/{id}/schedule`, POST `.../schedule/tick` — хук для Celery beat | `app/services/scheduler.py` |
| Закрытый eval-набор (13.2, D-07) | Отсутствовал | 84 сценария: 22 бухгалтер / 21 юрист / 21 безопасник / 20 смешанных E2E — выше минимумов ТЗ; каждый сценарий фиксирует ожидаемое состояние, решение Policy Gate, след Консультант+, запретные эффекты; pytest-обёртка (по тесту на сценарий) + `scripts/run_evals.py` с отчётом | `tests/evals/`, `scripts/run_evals.py` |
| Сессии и приглашения (10.1) | Отсутствовали | Refresh-токены (хешированные, ротация, revocation, детекция повторного использования с отзывом цепочки), HMAC access-токены с TTL 15 мин и session_secret без дефолта, приглашения с сервер-назначенной ролью и однократным принятием; принятие приглашения сразу выдаёт access/refresh пару; auth_mode=token/oidc | `app/services/sessions.py`, `app/api/v1/auth.py`, миграция 0021 |
| Append-only на уровне БД | Только приложением | Триггеры/RULE запрещают UPDATE/DELETE журналов аудита и поисков КонсультантПлюс (миграция 0020); проверено на живом PostgreSQL | миграция 0020 |
| Approval ledger (APR-001..004) | Частично | policy_version, machine requester, причина решения, идемпотентный replay | миграция 0012 |
| API для UI | — | `GET /api/v1/legal/provider-status`, `POST /api/v1/legal/search`, runtime-эндпоинты | `app/api/v1/legal.py`, `reviews.py` |
| Object storage (9.5) | Локальный каталог | Абстракция ObjectStorage: локальный каталог (по умолчанию) и S3/MinIO-бэкенд (boto3), фабрика по настройкам; загрузка/скачивание/удаление работают через оба бэкенда; ключи namespaced и валидируются; MinIO в compose под профилем `s3`; интеграционные тесты против реального MinIO (opt-in TEST_S3_URL) | `app/storage/`, миграций не требует |

Также: мёртвый legacy-путь исполнения office-flow удалён; mock-датасет v6 содержит
крупный счёт `inv_101` (242 000 ₽) для E2E-ветки approval.

## Проверки

Прогон 2026-10-07 локально на этой копии (SQLite, без Docker и MinIO).

- `ruff check` — 0 ошибок; `ruff format --check` — 276 файлов чисто; `mypy --strict` — 0 ошибок.
- Backend: **485 passed, 16 skipped** (локальный SQLite-прогон; skipped = PostgreSQL,
  MinIO и real-model opt-in). PostgreSQL и MinIO запускаются отдельными обязательными
  шагами CI.
- Eval-отчёт: `scripts/run_evals.py` → 84 passed / 0 failed; минимумы ТЗ 13.2 выполнены по всем доменам.
- Golden values ACC-01: tests/unit/golden_values.json — тест-сверка детерминированных расчётов.
- Beat: `ai_office.run_due_schedules` каждые 5 минут (отключено до подписи владельцем); runbooks — docs/RUNBOOKS.md (D-09).
- Frontend: **25/25** node:test + успешный `npm run build` (269 kB JS entry / 82 kB gzip, плюс 6 lazy-чанков 29 kB и 46 kB CSS).
- Миграции 0001→0023 применяются на пустую БД, один head (`20261005_0023`); CI проверяет
  `alembic upgrade head` и `alembic check` на PostgreSQL.

Известные хрупкие шаги (не блокируют, но ловятся не на каждом прогоне):

- `tests/integration/test_migrations.py::test_initial_migration_roundtrip` поднимает три
  дочерних процесса `alembic` (upgrade head → downgrade base → upgrade head), каждый с
  фиксированным `timeout=30`. На загрузке CPU шаг не укладывается в лимит и падает с
  `TimeoutExpired`: наблюдались и одиночный провал файла, и провал внутри полного
  `pytest -q`; на свободной машине те же три шага занимают ~24 с. Тест не менял
  утверждений — это граница тайминга харнесса, отдельная правка по явному запросу.
- `scripts/smoke_local.py` на Windows завершается с ошибкой на остановке сервера:
  `taskkill /PID <pid> /T /F` возвращает 255, хотя сам smoke-сценарий отработал.
- Docker-сборка локально не проверялась (Docker Desktop в этой среде недоступен).
  Перестановка слоёв в `Dockerfile` от 2026-10-07 — Dependencies ставятся до `COPY app`,
  проект больше не устанавливается в site-packages, импорт закрыт `ENV PYTHONPATH=/app` —
  помечена как неверифицированная; собирающим её проверка остаётся CI-шаг
  `docker compose up -d --build`.

## Соответствие критериям приёмки (частичное)

- ACC-03 (Консультант+), ACC-04/ACC-05 (approval/company isolation), ACC-08 (DAG/stop-lines),
  ACC-10 (kill switch → ручной режим) — автоматизированные тесты есть.
- ACC-01/ACC-02 (эталоны, маршрутизация), ACC-06 (egress), ACC-07 (restart), ACC-09 (экономика)
  — частично, требуют закрытого набора сценариев из ТЗ 13.2.

## Не сделано (следующие шаги)

1. **Production-режим `require_fresh_snapshot`** расписания — включается
   владельцем после согласования окна выгрузки 1С (runbook: docs/RUNBOOKS.md).
2. Эталонные значения 1С от заказчика для ACC-01 на реальных данных —
   внутренний эталон уже зафиксирован (tests/unit/golden_values.json).
3. Шифрование бакета MinIO/S3 на стороне инфраструктуры (SSE) — включается
   конфигурацией хранилища, код уже готов.
4. Настройка production IdP и browser redirect/PKCE вместо пилотного обмена
   готового OIDC assertion через `/api/v1/auth/oidc/session`.

## Запуск проверок

```bash
uv sync --offline            # или uv sync при доступе к сети
uv run ruff check . && uv run ruff format --check . && uv run mypy app
uv run pytest -q
TEST_POSTGRES_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/ai_office_test" \
  uv run pytest tests/postgres -q
```
