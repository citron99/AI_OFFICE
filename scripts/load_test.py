"""Load proof for the TZ 1.2/11.3 scale point: 300 tasks per day.

Runs against PostgreSQL (the production database), applying real migrations
to a throwaway database, then submits N tasks with concurrent workers and
verifies every task reaches a terminal state exactly once with intact
idempotency. Reports wall time and throughput.

    TEST_POSTGRES_URL="postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/postgres" \
        uv run python scripts/load_test.py --tasks 300 --workers 10
"""

import argparse
import asyncio
import time
from collections import Counter
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config

TERMINAL = {
    "completed",
    "waiting_approval",
    "waiting_input",
    "waiting_source",
    "failed_safe",
    "cancelled",
    "failed",
}


async def _prepare_database(base_url: str, load_db: str) -> None:
    """Drop and recreate the load database, then apply migrations."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(base_url, isolation_level="AUTOCOMMIT")
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP DATABASE IF EXISTS "{load_db}"'))
        await connection.execute(text(f'CREATE DATABASE "{load_db}"'))
    await engine.dispose()

    from sqlalchemy.ext.asyncio import create_async_engine as _engine

    load_url = base_url.rsplit("/", 1)[0] + f"/{load_db}"
    # __file__ is absolute under the supported launchers; avoid synchronous
    # filesystem resolution inside the async load-test path.
    root = Path(__file__).parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))

    async def run_migrations() -> None:
        engine = _engine(load_url)

        def _migrate(sync_connection) -> None:  # type: ignore[no-untyped-def]
            config.attributes["connection"] = sync_connection
            command.upgrade(config, "head")

        async with engine.begin() as connection:
            await connection.run_sync(_migrate)
        await engine.dispose()

    await run_migrations()


async def _drop_database(base_url: str, load_db: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(base_url, isolation_level="AUTOCOMMIT")
    async with engine.begin() as connection:
        await connection.execute(text(f'DROP DATABASE IF EXISTS "{load_db}"'))
    await engine.dispose()


async def submit_and_wait(
    client: httpx.AsyncClient,
    index: int,
    semaphore: asyncio.Semaphore,
) -> tuple[str, str]:
    idempotency_key = f"load-{index:04d}"
    payloads = [
        {
            "message": "Проверь счёт и платежи",
            "invoice_id": "inv_100",
            "requested_action": "prepare_payment_draft",
            "jurisdiction": "LV",
            "effective_on": "2026-08-27",
        },
        {
            "message": "contract payment acceptance",
            "jurisdiction": "LV",
            "effective_on": "2026-08-27",
        },
        {"message": "Проверь текст на секреты", "requested_agent": "security"},
        {
            "message": "Ежедневный контроль денег",
            "process_id": "daily_cash_and_receivable_risk",
            "effective_on": "2026-08-27",
        },
    ]
    payload = payloads[index % len(payloads)]
    async with semaphore:
        created = await client.post(
            "/api/v1/tasks", json=payload, headers={"Idempotency-Key": idempotency_key}
        )
        if created.status_code != 201:
            return "submit_failed", f"HTTP {created.status_code}"
        task = created.json()
        task_id = task["task_id"]
        deadline = time.monotonic() + 600
        while task["state"] not in TERMINAL:
            if time.monotonic() > deadline:
                return "timeout", task_id
            await asyncio.sleep(0.05)
            response = await client.get(f"/api/v1/tasks/{task_id}")
            task = response.json()
        replay = await client.post(
            "/api/v1/tasks", json=payload, headers={"Idempotency-Key": idempotency_key}
        )
        if replay.json().get("task_id") != task_id:
            return "idempotency_broken", task_id
        return "ok", task_id


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=int, default=300)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument(
        "--postgres-url",
        default="postgresql+asyncpg://postgres:postgres@127.0.0.1:5433/postgres",
    )
    args = parser.parse_args()

    from app.config import Settings
    from app.db.session import create_engine, create_session_factory
    from app.main import create_app

    load_db = "ai_office_load"
    await _prepare_database(args.postgres_url, load_db)
    database_url = args.postgres_url.rsplit("/", 1)[0] + f"/{load_db}"

    engine = create_engine(database_url)
    settings = Settings(
        app_env="test",
        database_url=database_url,
        llm_provider="mock",
        embedding_provider="mock",
        upload_dir=Path("tmp-load-uploads"),
        rate_limit_enabled=False,  # the proof targets throughput, not shedding
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    semaphore = asyncio.Semaphore(args.workers)
    started = time.monotonic()
    results: list[tuple[str, str]] = []

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://load") as client:
            tasks = [
                asyncio.create_task(submit_and_wait(client, index, semaphore))
                for index in range(args.tasks)
            ]
            done = 0
            for finished in asyncio.as_completed(tasks):
                results.append(await finished)
                done += 1
                if done % 50 == 0:
                    print(f"  ... {done}/{args.tasks} ({time.monotonic() - started:.0f}s)")
    elapsed = time.monotonic() - started

    statuses = Counter(status for status, _ in results)
    task_ids = [task_id for status, task_id in results if status == "ok"]
    duplicates = len(task_ids) - len(set(task_ids))
    print(f"Submitted: {args.tasks} tasks, {args.workers} workers")
    print(f"Wall time: {elapsed:.1f}s ({args.tasks / elapsed:.1f} tasks/s)")
    print(f"Outcomes: {dict(statuses)}")
    print(f"Unique task ids: {len(set(task_ids))}/{len(task_ids)} (duplicates: {duplicates})")
    ok = statuses["ok"] == args.tasks and duplicates == 0
    print("PASS: 300 tasks/day scale point proven on PostgreSQL" if ok else "FAIL")
    await engine.dispose()
    await _drop_database(args.postgres_url, load_db)
    return 0 if ok else 1


if __name__ == "__main__":
    import sys

    sys.exit(asyncio.run(main()))
