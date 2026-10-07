# Проверка PostgreSQL и pgvector

Тесты `tests/postgres` требуют отдельной тестовой БД и явного `TEST_POSTGRES_URL`.
Без него они пропускаются; `DATABASE_URL` приложения не используется как fallback.
Не задавайте production URL. Пользователю БД нужны права создания схем и extension vector.

Каждый тест создаёт случайную схему `ai_office_test_<uuid>` и применяет в ней миграции.
Таблица Alembic также находится в этой схеме, независимо от `public.alembic_version`.
После теста удаляется только созданная схема. Extension в public сохраняется.
При принудительном завершении процесса схема может остаться: используйте одноразовую БД.

Проверяются реальные SQL-запросы, а не mock базы данных:

- поиск среди векторов 128D и 3D с фильтрацией модели, владельца и юрисдикции;
- два одновременных запроса переиндексации через независимые сессии: одна копия и один набор чанков;
- downgrade до 0003 и upgrade до head с сохранением исходных 128D-векторов.

Векторы тестовые: это не оценка семантического или юридического качества.

## Прямой запуск

```powershell
$env:TEST_POSTGRES_URL = "postgresql+asyncpg://postgres:test_password@127.0.0.1:5432/ai_office_test"
uv run --no-sync pytest -q tests/postgres
```

## Linux-контейнер на Windows

Требуется работающий Docker Desktop в режиме Linux containers. Сборка загружает зависимости
из lock-файла, но не загружает semantic-модель и не вызывает внешний LLM.
Имена ниже предназначены для новых одноразовых ресурсов; при конфликте выберите другие.

```powershell
docker build -f Dockerfile.test -t ai-office-tests:local .
docker run --rm -d --name ai-office-test-db -e POSTGRES_PASSWORD=local_test_only -e POSTGRES_DB=ai_office_test pgvector/pgvector:pg16
docker exec ai-office-test-db pg_isready -U postgres -d ai_office_test
```

Дождитесь `accepting connections`, затем выполните полный набор:

```powershell
docker run --rm --network container:ai-office-test-db -e TEST_POSTGRES_URL=postgresql+asyncpg://postgres:local_test_only@127.0.0.1:5432/ai_office_test ai-office-tests:local
docker run --rm ai-office-tests:local uv run --no-sync python scripts/eval_retrieval.py --check
docker run --rm ai-office-tests:local uv run --no-sync python scripts/smoke_local.py
```

Порты БД не публикуются на хосте; контейнер тестов использует её сетевое пространство.
Smoke проверяет настоящий HTTP-сервер с временной SQLite БД, eval — синтетическую mock-регрессию.
После проверки остановите именно одноразовую БД:

```powershell
docker stop ai-office-test-db
```

Контейнер запущен с `--rm` без томов: его тестовые данные удаляются без восстановления.
Повторный запуск создаёт новую БД. Тестовый образ остаётся для следующих прогонов.

## Подтверждённый результат, 2026-08-27

Linux/Python 3.12: **118 passed**, включая три теста настоящего PostgreSQL 16/pgvector.
HTTP smoke и eval `--check` прошли. Ruff, format и mypy прошли на хосте.
В Windows Python соединения сбрасывались с WinError 10054; настройки сети и asyncio
приложения не менялись. Проверки добавлены в CI, удалённый runner в этом этапе не запускался.
