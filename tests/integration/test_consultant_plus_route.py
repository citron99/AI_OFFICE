"""Integration coverage: mandatory Consultant+ route (LEG-001..008)."""

import hashlib
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.session import create_session_factory
from app.db.tables.consultant_plus import ConsultantPlusSearchEventRecord
from app.main import create_app


async def _legal_task(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/tasks",
        json={
            "message": "contract payment acceptance",
            "jurisdiction": "LV",
            "effective_on": "2026-08-27",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_legal_route_records_consultant_trail(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    task = await _legal_task(client)
    assert task["state"] == "completed"
    result = task["result"]
    trail = result["consultant_plus"]
    assert trail["searched"] is True
    assert trail["mode"] == "mock"
    assert trail["queries"], "the licensed channel must return metadata for the query"
    first = trail["queries"][0]
    assert first["jurisdiction"] == "LV"
    assert first["edition"]
    assert first["locator"]
    assert first["query_id"]
    async with create_session_factory(engine)() as session:
        events = list(
            await session.scalars(
                select(ConsultantPlusSearchEventRecord).where(
                    ConsultantPlusSearchEventRecord.task_id == task["task_id"]
                )
            )
        )
    assert len(events) == len(trail["queries"])
    assert {event.source_id for event in events} == {q["source_id"] for q in trail["queries"]}
    assert all(event.outcome == "found" for event in events)


async def test_provider_off_stops_legal_route_in_waiting_source(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    settings = Settings(
        app_env="test",
        upload_dir=tmp_path,
        consultant_plus_mode="off",
        auth_token_hashes={
            hashlib.sha256(b"test-owner").hexdigest(): {"user_id": "owner-off", "role": "owner"}
        },
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            c.headers["Authorization"] = "Bearer test-owner"
            task = await _legal_task(c)
            # The licensed channel is off: controlled stop, never a model answer.
            assert task["state"] == "waiting_source"
            assert task["result"]["status"] == "waiting_source"
            assert task["result"]["consultant_plus"]["searched"] is False
            assert task["result"]["findings"] == []
            async with create_session_factory(engine)() as session:
                events = list(
                    await session.scalars(
                        select(ConsultantPlusSearchEventRecord).where(
                            ConsultantPlusSearchEventRecord.task_id == task["task_id"]
                        )
                    )
                )
            assert len(events) == 1
            assert events[0].outcome == "unavailable"


async def test_legal_provider_status_endpoint(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/legal/provider-status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "mock"
    assert body["status"] == "ok"
    assert body["license_scope"]["jurisdictions"] == ["DE", "LV", "RU"]


async def test_legal_search_endpoint_returns_metadata_only(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/legal/search",
        json={
            "query": "contract payment acceptance",
            "jurisdiction": "LV",
            "effective_on": "2026-08-27",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["results"]
    assert set(body["results"][0]) == {
        "query_id",
        "source_id",
        "title",
        "jurisdiction",
        "document_type",
        "edition",
        "effective_from",
        "effective_to",
        "locator",
        "authority",
        "retrieved_at",
    }
    # A German query matches the DE official source inside the scope.
    approved = await client.post(
        "/api/v1/legal/search",
        json={
            "query": "Zahlung Vertrag Verzug",
            "jurisdiction": "DE",
            "effective_on": "2026-08-27",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["results"][0]["authority"] == "Synthetic Official Source (DE)"
    forbidden = await client.post(
        "/api/v1/legal/search",
        json={
            "query": "contract payment acceptance",
            "jurisdiction": "US",
            "effective_on": "2026-08-27",
        },
    )
    assert forbidden.status_code == 403
