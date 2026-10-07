"""Pytest wrapper: every closed-set scenario runs as one test with a fresh app."""

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

sys.path.insert(0, str(Path(__file__).parent))

from catalog import build_catalog, domain_counts  # noqa: E402
from runner import run_scenario  # noqa: E402

CATALOG = build_catalog()


def test_closed_set_meets_tz_minimums() -> None:
    """TZ 13.2: >=20 scenarios per domain agent and >=20 mixed E2E."""
    counts = domain_counts(CATALOG)
    assert counts.get("accountant", 0) >= 20
    assert counts.get("lawyer", 0) >= 20
    assert counts.get("security", 0) >= 20
    assert counts.get("mixed", 0) >= 20


@pytest.mark.parametrize("scenario", CATALOG, ids=[s["id"] for s in CATALOG])
async def test_closed_set_scenario(
    scenario: dict[str, Any],
    engine: AsyncEngine,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    from app.config import Settings
    from app.db.session import create_session_factory
    from app.main import create_app

    def build(settings: Settings) -> httpx.AsyncClient:
        application = create_app(
            settings=settings,
            engine=engine,
            session_factory=create_session_factory(engine),
        )
        return httpx.AsyncClient(  # noqa: SIM117
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        )

    default_settings = Settings(
        app_env="test",
        llm_provider="mock",
        embedding_provider="mock",
        upload_dir=tmp_path / "uploads",
        max_upload_bytes=1024 * 1024,
    )
    clients_by_app: dict[str, httpx.AsyncClient] = {"default": build(default_settings)}
    if scenario["input"].get("__app__") == "consultant_off":
        clients_by_app["consultant_off"] = build(
            default_settings.model_copy(update={"consultant_plus_mode": "off"})
        )

    client = clients_by_app[scenario["input"].get("__app__", "default")]
    apps = [c._transport.app for c in clients_by_app.values()]  # noqa: SLF001
    lifespans = [application.router.lifespan_context(application) for application in apps]
    try:
        for lifespan in lifespans:
            await lifespan.__aenter__()
        violations = await run_scenario(scenario, client, clients_by_app)
    finally:
        for lifespan in lifespans:
            await lifespan.__aexit__(None, None, None)
        for http in clients_by_app.values():
            await http.aclose()
    assert not violations, f"{scenario['id']}: " + "; ".join(violations)
