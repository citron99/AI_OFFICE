"""Synthetic crash-window probe: persist a task without publishing it to Redis."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.models.enums import AgentType
from app.models.task import TaskCreate
from app.repositories.tasks import TaskRepository


async def main(url: str) -> None:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            record = await TaskRepository(session).create(
                user_id="usr_demo_owner",
                payload=TaskCreate(
                    message="SYNTHETIC recovery security check", requested_agent=AgentType.SECURITY
                ),
            )
            record.updated_at = datetime.now(UTC) - timedelta(minutes=1)
            await session.commit()
            task_id = record.id
        async with httpx.AsyncClient(base_url=url, timeout=10) as client:
            async with asyncio.timeout(60):
                while True:
                    response = await client.get(f"/api/v1/tasks/{task_id}")
                    response.raise_for_status()
                    task = response.json()
                    if task["state"] == "completed":
                        assert task["result"]["security"]["external_transmission_allowed"] is False
                        print("PASS: persisted-only task recovered by dispatcher and worker")
                        print(f"Synthetic task: {task_id}")
                        return
                    if task["state"] in {"failed", "cancelled"}:
                        raise RuntimeError("Recovery did not complete")
                    await asyncio.sleep(0.5)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    asyncio.run(main(parser.parse_args().url))
