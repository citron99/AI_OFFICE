# Runbooks эксплуатации (D-09, ТЗ V2.1 раздел 15.1)

Каждый runbook проверяем: команды выполнимы против `docker-compose.yml`
репозитория, состояния воспроизводимы через API.

## 1. Развёртывание

```bash
# Полный стек: postgres+pgvector, redis, api, dispatcher (celery worker), frontend
docker compose up -d --build
docker compose exec api alembic upgrade head        # миграции 0001→0019
curl -fsS localhost:8000/ready                      # {"status":"ready",...}

# Создание принципалов (demo-режим: AUTH_MODE=demo; api-key режим см. app/config.py)
# AUTH_TOKEN_HASHES: {"<sha256(token)>": {"user_id": "...", "role": "owner", "company_id": "comp_demo"}}
```

Проверка после деплоя: `GET /api/v1/legal/provider-status` → mode/status;
`GET /api/v1/processes/{id}/runtime` → переключатели; эталонный прогон —
`uv run pytest tests/evals -q` и `uv run python scripts/run_evals.py`.

## 2. Kill switch и переход в ручной режим (ACC-10)

```bash
# Немедленная остановка процесса (владелец, роль owner):
curl -X POST /api/v1/processes/office_review/runtime \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -d '{"process_enabled": false}'
# Новые запуски паркуются в WAITING_INPUT со статусом stopped_by_switch;
# выполняющиеся шаги безопасно завершаются, внешних действий нет.

# Точечные выключатели:
curl -X POST .../runtime -d '{"llm_enabled": false}'          # внешний LLM
curl -X POST .../runtime -d '{"write_tools_enabled": false}'  # write tools (DENY)

# Возврат: те же вызовы с true. Активную задачу из ручного режима
# возобновляют через POST /api/v1/tasks/{id}/retry (с последнего checkpoint).
```

Понижение уровня автономности — тем же эндпоинтом (`autonomy_level`),
не выше потолка паспорта процесса (`processes/*.v3.json`).

## 3. Недоступность провайдеров

| Провайдер | Поведение системы | Действия дежурного |
| --- | --- | --- |
| 1С | Задачи стоят в WAITING_INPUT/FAILED_SAFE; включите `require_fresh_snapshot` в расписании, чтобы не считать по старым данным | Проверить окно выгрузки, затем `POST /processes/{id}/schedule/tick` |
| КонсультантПлюс | Юридические маршруты → WAITING_SOURCE, финальный вывод запрещён | Проверить лицензированный канал; после восстановления retry задачи |
| LLM | Retry по RetryPolicy → FAILED_SAFE + DLQ | `SELECT * FROM dead_letter_entries WHERE resolved=false;` → разбор → `POST /tasks/{id}/retry` (продолжение с checkpoint) |

Проверка восстановления: `pytest tests/integration/test_reliability.py` —
покрывает restart во время provider call и возобновление с checkpoint.

## 4. Backup / restore (PostgreSQL)

```bash
docker compose exec postgres pg_dump -U postgres ai_office > backup_$(date +%F).sql
# Restore: остановить api/dispatcher, восстановить, поднять, прогнать миграции:
docker compose exec -T postgres psql -U postgres ai_office < backup_2026-09-08.sql
docker compose exec api alembic current   # версия должна совпадать с кодом
```

RPO/RTO фиксируются владельцем до пилота (ТЗ 11.3); тест восстановления
обязателен до production-пилота.

## 5. Инциденты безопасности

- Секрет/RESTRICTED в логах: классификатор и DLP не пропускают такой контент
  в задачи и хранилище (`tests/integration/test_egress_gateway.py`); при
  подозрении — `SELECT * FROM audit_events WHERE event LIKE 'approval_%'`
  и egress-журнал; инцидент фиксируется отдельным append-only событием.
- Подозрение на компрометацию статического API-ключа: ротация
  `AUTH_TOKEN_HASHES` и перезапуск API. Для `token`/`oidc` — logout/отзыв
  refresh-сессии либо отключение user/membership: привязанный access token
  становится недействительным сразу после изменения в БД.
- Cross-company чтение объектов возвращает 404; неактивная сессия или
  членство — 401. Регулярно просматривайте `audit_events` и журналы API.

OIDC связывает локального пользователя с `(issuer, sub)`, а не с email.
Старые пилотные OIDC-записи, созданные по email без этой привязки, не
подхватываются автоматически: при конфликте адреса вход закрывается с 401.
Миграция таких записей требует подтверждения субъекта у IdP и переноса
связанных user ID администратором; автоматическое объединение по email запрещено.

## 6. Планировщик

Расписание отключено по умолчанию. Включение — только владельцем:

```bash
curl -X PUT /api/v1/processes/daily_cash_and_receivable_risk/schedule \
  -d '{"process_id":"daily_cash_and_receivable_risk","enabled":true,
       "timezone":"Europe/Riga","run_at":"08:30","workdays_only":true}'
```

Beat запускается dispatcher-сервисом (`celery beat`, интервал 5 минут).
Для production после согласования окна выгрузки 1С включите
`require_fresh_snapshot: true` и `snapshot_max_lag_hours`.
