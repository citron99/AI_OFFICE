"""Create one synthetic approval and backdate only its TTL to probe housekeeping."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.db.tables.approvals import ApprovalRecord


async def main(url: str) -> None:
    engine = create_engine(get_settings().database_url)
    try:
        async with httpx.AsyncClient(base_url=url, timeout=10) as client:
            response = await client.post(
                "/api/v1/tasks",
                json={
                    "message": "SYNTHETIC invoice expiry probe",
                    "invoice_id": "inv_100",
                    "requested_action": "prepare_payment_draft",
                    "effective_on": "2026-08-27",
                },
            )
            response.raise_for_status()
            task_id = response.json()["task_id"]
            async with asyncio.timeout(60):
                while True:
                    response = await client.get(f"/api/v1/tasks/{task_id}")
                    response.raise_for_status()
                    task = response.json()
                    if task["state"] == "waiting_approval":
                        break
                    if task["state"] in {"failed", "cancelled", "completed"}:
                        raise RuntimeError("Synthetic task did not request approval")
                    await asyncio.sleep(0.5)
            approval_id = task["result"]["approval_id"]
            async with create_session_factory(engine)() as session:
                approval = await session.get(ApprovalRecord, approval_id)
                assert approval and approval.task_id == task_id
                assert approval.owner_id == "usr_demo_owner" and approval.status == "pending"
                approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await session.commit()
            async with asyncio.timeout(60):
                while True:
                    response = await client.get(f"/api/v1/tasks/{task_id}")
                    response.raise_for_status()
                    task = response.json()
                    if task["state"] == "completed":
                        assert task["result"]["status"] == "approval_expired"
                        assert task["result"]["draft_id"] is None
                        assert task["result"]["requires_approval"] is False
                        print("PASS: dispatcher expired synthetic approval without a draft")
                        print(f"Synthetic task: {task_id}")
                        return
                    await asyncio.sleep(0.5)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    asyncio.run(main(parser.parse_args().url))
