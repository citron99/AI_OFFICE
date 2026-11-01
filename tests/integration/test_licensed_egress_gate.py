"""Licensed Consultant+ traffic passes the egress gateway and is journaled per tenant.

Covers п.8 of the manual search / change-radar surfaces: before this wave the
provider was called directly, so tenant text could leave the perimeter with no
gate and no `ConsultantPlusSearchEventRecord`, while the task graph already
journaled its trail.
"""

from datetime import date
from pathlib import Path

import httpx
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.session import create_session_factory
from app.db.tables.consultant_plus import ConsultantPlusSearchEventRecord
from app.db.tables.legal_change import LegalChangeRadarRunRecord
from app.integrations.consultant_plus.mock import MockConsultantPlusProvider
from app.integrations.consultant_plus.models import (
    ConsultantPlusDocument,
    ConsultantPlusSearchResult,
    LicenseScope,
    ProviderHealth,
)
from app.main import create_app

RESTRICTED_QUERY = "contract payment acceptance password=Sup3rS3cretX"
CLEAN_QUERY = "contract payment acceptance"


class SpyConsultant:
    """Counts every call that would cross the perimeter."""

    mode = "licensed"

    def __init__(self) -> None:
        self._inner = MockConsultantPlusProvider()
        self.queries: list[str] = []

    def search(
        self, *, query: str, jurisdiction: str, effective_on: date, limit: int = 5
    ) -> list[ConsultantPlusSearchResult]:
        self.queries.append(query)
        return self._inner.search(
            query=query, jurisdiction=jurisdiction, effective_on=effective_on, limit=limit
        )

    def get_document(self, document_id: str, *, edition: str) -> ConsultantPlusDocument:
        return self._inner.get_document(document_id, edition=edition)

    def get_citation(self, locator: str) -> ConsultantPlusSearchResult:
        return self._inner.get_citation(locator)

    def healthcheck(self) -> ProviderHealth:
        return self._inner.healthcheck()

    def license_scope(self) -> LicenseScope | None:
        return self._inner.license_scope()


async def _events(engine: AsyncEngine) -> list[ConsultantPlusSearchEventRecord]:
    async with create_session_factory(engine)() as session:
        return list(
            await session.scalars(
                select(ConsultantPlusSearchEventRecord).order_by(
                    ConsultantPlusSearchEventRecord.searched_at
                )
            )
        )


@pytest_asyncio.fixture
async def gate(engine: AsyncEngine, tmp_path: Path) -> tuple[httpx.AsyncClient, SpyConsultant]:
    settings = Settings(
        app_env="test",
        upload_dir=tmp_path / "uploads",
        auto_create_schema=False,
        max_upload_bytes=4096,
    )
    app = create_app(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
    )
    spy = SpyConsultant()
    async with app.router.lifespan_context(app):
        app.state.consultant_provider = spy
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
            yield api_client, spy


async def _search(client: httpx.AsyncClient, query: str) -> httpx.Response:
    return await client.post(
        "/api/v1/legal/search",
        json={"query": query, "jurisdiction": "LV", "effective_on": "2026-08-27"},
    )


async def _seed_radar_sources(client: httpx.AsyncClient) -> tuple[str, str]:
    ids: list[str] = []
    for filename, text, version, effective_from, status in (
        ("old.txt", "Payment is due monthly.", "2025.1", "2025-01-01", "SUPERSEDED"),
        ("new.txt", "Payment is due weekly.", "2026.1", "2026-01-01", "ACTIVE"),
    ):
        uploaded = await client.post(
            "/api/v1/files", files={"file": (filename, text.encode(), "text/plain")}
        )
        assert uploaded.status_code == 201, uploaded.text
        created = await client.post(
            "/api/v1/knowledge/sources",
            json={
                "artifact_id": uploaded.json()["id"],
                "title": "Synthetic contract regulation",
                "jurisdiction": "LV",
                "document_type": "regulation",
                "authority": "Synthetic authority",
                "version": version,
                "effective_from": effective_from,
                "status": status,
            },
        )
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])
    return ids[0], ids[1]


async def test_restricted_query_never_reaches_the_licensed_provider(
    engine: AsyncEngine, gate: tuple[httpx.AsyncClient, SpyConsultant]
) -> None:
    client, spy = gate
    response = await _search(client, RESTRICTED_QUERY)
    assert response.status_code == 403, response.text
    assert spy.queries == []
    events = await _events(engine)
    assert len(events) == 1
    assert events[0].outcome == "egress_blocked"
    assert events[0].company_id == "comp_demo"
    assert events[0].owner_id == "usr_demo_owner"
    assert events[0].task_id is None
    assert "Sup3rS3cretX" not in str(events[0].details)


async def test_allowed_query_is_journaled_with_tenant_and_user(
    engine: AsyncEngine, gate: tuple[httpx.AsyncClient, SpyConsultant]
) -> None:
    client, spy = gate
    response = await _search(client, CLEAN_QUERY)
    assert response.status_code == 200, response.text
    assert response.json()["results"]
    assert spy.queries == [CLEAN_QUERY]
    events = await _events(engine)
    assert events
    assert {event.outcome for event in events} == {"found"}
    assert {event.company_id for event in events} == {"comp_demo"}
    assert {event.owner_id for event in events} == {"usr_demo_owner"}
    assert {event.jurisdiction for event in events} == {"LV"}


async def test_allowed_query_without_hits_is_still_journaled(
    engine: AsyncEngine, gate: tuple[httpx.AsyncClient, SpyConsultant]
) -> None:
    """A crossing that returns nothing must not look like a call that never happened."""
    client, spy = gate
    response = await _search(client, "arbitration clause")
    assert response.status_code == 200, response.text
    assert response.json()["results"] == []
    assert spy.queries == ["arbitration clause"]
    events = await _events(engine)
    assert [event.outcome for event in events] == ["not_found"]
    assert events[0].company_id == "comp_demo"
    assert events[0].owner_id == "usr_demo_owner"
    assert events[0].jurisdiction == "LV"
    assert events[0].details["decision"] == "allow"


async def test_legal_task_route_never_calls_the_provider(
    engine: AsyncEngine, gate: tuple[httpx.AsyncClient, SpyConsultant]
) -> None:
    """The agent graph stops at the gateway, not only the manual HTTP surface."""
    client, spy = gate
    response = await client.post(
        "/api/v1/tasks",
        json={
            "message": RESTRICTED_QUERY,
            "jurisdiction": "LV",
            "effective_on": "2026-08-27",
        },
    )
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["state"] == "waiting_source", task
    assert spy.queries == []
    assert task["result"]["consultant_plus"]["searched"] is False
    assert task["result"]["consultant_plus"]["egress_decision"] == "block"
    assert task["result"]["findings"] == []
    events = await _events(engine)
    assert [event.outcome for event in events] == ["egress_blocked"]
    assert events[0].task_id == task["task_id"]
    assert events[0].company_id == "comp_demo"
    assert "Sup3rS3cretX" not in str(events[0].details)


async def test_radar_subject_passes_the_same_gate(
    engine: AsyncEngine, gate: tuple[httpx.AsyncClient, SpyConsultant]
) -> None:
    client, spy = gate
    baseline_id, current_id = await _seed_radar_sources(client)
    response = await client.post(
        "/api/v1/legal/change-radar/runs",
        json={
            "baseline_source_id": baseline_id,
            "current_source_id": current_id,
            "subject": RESTRICTED_QUERY,
            "jurisdiction": "LV",
            "effective_on": "2026-08-27",
        },
        headers={"Idempotency-Key": "radar-egress-001"},
    )
    assert response.status_code == 403, response.text
    assert spy.queries == []
    async with create_session_factory(engine)() as session:
        runs = await session.scalar(select(func.count()).select_from(LegalChangeRadarRunRecord))
    assert int(runs or 0) == 0
    events = await _events(engine)
    assert [event.outcome for event in events] == ["egress_blocked"]
