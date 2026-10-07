# AI-офис собственника

Portfolio case: **Legal Change Radar** compares versioned legal sources with tenant isolation,
effective-date gates, Consultant+ metadata verification, exact before/after citations,
idempotent runs and an append-only lawyer/owner review trail.

Локальный интегрированный пилот: React, FastAPI, PostgreSQL/pgvector, Redis/Celery,
юридическая база знаний, синтетическая бухгалтерия, проверка чувствительных данных
и согласование mock-черновиков. Реальные платежи и production-интеграция с 1С не используются.
Это ещё не принятый в промышленную эксплуатацию продукт.

## Что внутри (ТЗ V2.1)

- Детерминированный Policy Gate с лимитами 100 000/200 000 руб. (ALLOW_DRAFT /
  REQUIRE_OWNER_APPROVAL / DENY / ESCALATE); реальный платёж всегда вне агентов.
- Обязательный поиск в КонсультантПлюс перед любым юридическим анализом
  (WAITING_SOURCE / LEGAL_SOURCE_NOT_FOUND вместо ответа из памяти модели).
- Исполнение DAG с таймаутами, bounded retry, FAILED_SAFE, DLQ и возобновлением
  с checkpoint; идемпотентность в пределах company_id.
- Компании и изоляция данных; machine identities агентов с короткоживущими
  capability grants; kill switch и лестница автономности A0–A3.
- Data Egress Gateway (классы данных PUBLIC..RESTRICTED), DLP и антивирусный
  контент-скан при загрузке, object storage (локально или S3/MinIO).
- Закрытый eval-набор (84 сценария) и golden-значения ACC-01.

## Документация

| Документ | Содержимое |
| --- | --- |
| [docs/INTEGRATION_STATUS.md](docs/INTEGRATION_STATUS.md) | что реализовано и что осталось |
| [docs/DELIVERY.md](docs/DELIVERY.md) | карта поставки D-01..D-11 |
| [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) | RBAC, потоки данных, threat model |
| [docs/RUNBOOKS.md](docs/RUNBOOKS.md) | kill switch, ручной режим, отказы, backup |

## Быстрый старт

Требуется работающий Docker Desktop. Все внешние порты привязаны к loopback.

```powershell
docker compose -p ai-office-demo up -d --build
```

Откройте http://127.0.0.1:8080. API: http://127.0.0.1:8000/docs.
Миграции запускаются автоматически; данные сохраняются в Docker volumes.
По умолчанию это один demo owner без пароля — только синтетические документы.
Подробности эксплуатации и ограничения: [docs/OPERATIONS.md](docs/OPERATIONS.md).
Финансовые отчёты и формулы: [docs/FINANCIAL_REPORTS.md](docs/FINANCIAL_REPORTS.md).

Если порты заняты, задайте другие host-порты перед запуском:

```powershell
$env:AI_OFFICE_API_PORT = "8001"
$env:AI_OFFICE_FRONTEND_PORT = "8081"
docker compose -p ai-office-demo up -d --build
```

Проверка (Python 3.12 и `uv` для скрипта):

```powershell
uv sync --locked --dev
uv run python scripts/smoke_office.py
```

## Команды качества

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest -q
uv run python scripts/eval_retrieval.py --check
uv run python scripts/smoke_local.py
Push-Location frontend
npm test
npm run build
Pop-Location
```

## Реализованный объём

- TASK-001–005: bootstrap, конфигурация и FastAPI;
- TASK-006–013: async persistence, базовые таблицы и repository;
- TASK-014–017: Task API и state machine;
- TASK-018–021: LLM abstraction и mock provider; Anthropic adapter пока частичный;
- TASK-022–026: BaseAgent, DummyAgent, Orchestrator и technical E2E.

Добавлены инкременты TASK-031–044: Legal KB, извлечение TXT/PDF/DOCX,
фильтрованный поиск и LawyerAgent с опциональным LLM-анализом и проверкой цитат.
Это пилот, не завершённый production-ready юридический агент.
API и ограничения: [docs/LEGAL_RAG.md](docs/LEGAL_RAG.md).
Воспроизводимая оценка тестового поиска: [docs/RETRIEVAL_EVAL.md](docs/RETRIEVAL_EVAL.md).
Опциональный локальный semantic adapter и переиндексация: [docs/SEMANTIC_SEARCH.md](docs/SEMANTIC_SEARCH.md).
CPU-окружение и результаты настоящей модели: [docs/SEMANTIC_EVAL.md](docs/SEMANTIC_EVAL.md).

## Текущий статус и ограничения

File Service (TASK-027–030) добавлен: `POST /api/v1/files`, `GET /api/v1/files/{id}`,
SHA-256, проверка размера/расширения/MIME/signature и принадлежности вложения.
TXT и CSV должны быть UTF-8. Все документы считаются недоверенными данными.
Проверки формата не заменяют антивирус и изолированный parser.

Compose использует фоновую очередь; `EXECUTION_MODE=sync` оставлен для тестов.
Юридические задачи требуют `jurisdiction` и `effective_on`:
без них возвращается `waiting_input`, продолжение — `POST /api/v1/tasks/{id}/clarify`.
По умолчанию LawyerAgent возвращает источники. Вложения разбираются и участвуют в поиске,
но не становятся доверенными источниками KB. `LEGAL_ANALYSIS_ENABLED=true` включает
передачу извлечённого текста и источников настроенному LLM; включайте осознанно.
Ответ остаётся черновиком для юриста даже после проверки дословности цитат.
Бухгалтерия использует детерминированный Mock1C, SecurityAgent блокирует чувствительные данные
перед LLM. Неизвестные категории явно возвращают `unsupported`.
Есть UI, очередь, owner-scoped API, роли, согласование с TTL и журнал событий.

Аутентификация API-key доступна опционально; demo-режим не имеет пароля.
Режимы `token` и `oidc` используют короткоживущий access token и ротируемый
refresh token. Принятие приглашения сразу создаёт оба токена; refresh и logout
аутентифицируются самим refresh token и работают после истечения access token.
Во frontend доступны вход по API key, OIDC assertion и одноразовому приглашению;
учётные данные хранятся только в памяти вкладки.
`APP_ENV=production` запрещён до приёмки безопасности и качества.
Не открывайте сервер наружу и не загружайте реальные данные.
Порты Compose доступны только на loopback. Claude adapter — заготовка;
живые запросы, учёт токенов/стоимости и полноценная обработка API-ошибок ещё не проверены.
Поэтому TASK-019 и весь production-ready объём не считаются завершёнными.

## Полный локальный запуск в Docker

```powershell
docker compose up --build
```

Swagger UI: http://127.0.0.1:8000/docs

Без Docker (только demo/тесты на SQLite):

```powershell
uv sync --locked --dev
$env:DATABASE_URL = "sqlite+aiosqlite:///./ai_office.db"
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1
```

SQLite используется для быстрой локальной проверки, а не как замена PostgreSQL в целевой архитектуре.
CI содержит проверки миграций, pgvector и конкурентной переиндексации на PostgreSQL.
Изолированный запуск, в том числе через Linux-контейнер на Windows:
[docs/POSTGRES_TESTING.md](docs/POSTGRES_TESTING.md).
