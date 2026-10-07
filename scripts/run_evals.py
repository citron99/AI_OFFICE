"""Standalone closed-set runner: prints a per-domain report and exits nonzero on failure.

Usage:
    uv run python scripts/run_evals.py
"""

import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "evals"))

from catalog import build_catalog, domain_counts  # noqa: E402
from runner import run_scenario  # noqa: E402


async def main() -> int:
    from app.config import Settings
    from app.db.session import create_engine, create_session_factory
    from app.main import create_app

    catalog = build_catalog()
    print(f"Closed evaluation set: {len(catalog)} scenarios")
    counts = domain_counts(catalog)
    for domain, expected in (
        ("accountant", 20),
        ("lawyer", 20),
        ("security", 20),
        ("mixed", 20),
    ):
        actual = counts.get(domain, 0)
        status = "OK" if actual >= expected else "BELOW MINIMUM"
        print(f"  {domain:<11} {actual:>3} scenarios (minimum {expected}) {status}")

    engine = create_engine("sqlite+aiosqlite:///:memory:")
    settings = Settings(
        app_env="test",
        llm_provider="mock",
        embedding_provider="mock",
        upload_dir=Path("tmp-eval-uploads"),
    )
    application = create_app(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
    )
    # The standalone runner owns its schema: create it before the lifespan.
    from app.db.base import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    failures: list[tuple[str, list[str]]] = []
    off_settings = settings.model_copy(update={"consultant_plus_mode": "off"})
    off_engine = create_engine("sqlite+aiosqlite:///:memory:")
    off_app = create_app(
        settings=off_settings,
        engine=off_engine,
        session_factory=create_session_factory(off_engine),
    )
    async with off_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with (
        application.router.lifespan_context(application),
        off_app.router.lifespan_context(off_app),
    ):
        from httpx import ASGITransport, AsyncClient

        async with (
            AsyncClient(transport=ASGITransport(app=application), base_url="http://eval") as client,
            AsyncClient(transport=ASGITransport(app=off_app), base_url="http://eval") as off_client,
        ):
            clients = {"default": client, "consultant_off": off_client}
            for scenario in catalog:
                violations = await run_scenario(scenario, client, clients)
                mark = "PASS" if not violations else "FAIL"
                print(f"  [{mark}] {scenario['id']}: {scenario['title']}")
                if violations:
                    for violation in violations:
                        print(f"         - {violation}")
                    failures.append((scenario["id"], violations))
    await engine.dispose()

    verdict = Counter({"PASS": len(catalog) - len(failures), "FAIL": len(failures)})
    print(f"\nResult: {verdict['PASS']} passed, {verdict['FAIL']} failed")
    if failures:
        print("Failed scenarios:")
        for scenario_id, violations in failures:
            print(f"  {scenario_id}: {violations}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
