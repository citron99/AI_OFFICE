"""Observability metrics endpoint (TZ 9.2/12) and rate limiting (TZ 9.2)."""

import httpx

from app.config import Settings
from app.db.session import create_session_factory
from app.main import create_app


async def test_metrics_reports_operational_gauges(
    client: httpx.AsyncClient,
) -> None:
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"message": "security check", "requested_agent": "security"},
        )
    ).json()
    assert task["state"] in {"completed", "waiting_input"}
    response = await client.get("/api/v1/metrics")
    assert response.status_code == 200, response.text
    body = response.text
    # Prometheus exposition format with the operational gauges.
    assert "# TYPE ai_office_tasks_total gauge" in body
    assert 'ai_office_tasks_state{state="completed"}' in body
    assert "# TYPE ai_office_dlq_unresolved gauge" in body
    assert "# TYPE ai_office_approvals_pending gauge" in body
    assert "ai_office_consultant_search_events_total" in body
    assert "ai_office_sessions_active" in body
    # Content type is the text exposition format.
    assert "text/plain" in response.headers["content-type"]


async def test_metrics_counts_provider_latency_after_a_run(
    client: httpx.AsyncClient,
) -> None:
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"message": "security check", "requested_agent": "security"},
        )
    ).json()
    assert task["state"] in {"completed", "waiting_input"}
    body = (await client.get("/api/v1/metrics")).text
    assert 'ai_office_provider_calls_total{provider="security"}' in body
    assert 'ai_office_provider_latency_ms_sum{provider="security"}' in body


async def test_rate_limit_returns_429_after_threshold(engine, tmp_path) -> None:
    """TZ 9.2: the gateway sheds load with 429 + Retry-After."""
    import httpx

    settings = Settings(
        app_env="test",
        rate_limit_enabled=True,
        rate_limit_per_minute=3,
        upload_dir=tmp_path,
        llm_provider="mock",
        embedding_provider="mock",
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            codes = []
            for _ in range(5):
                response = await c.get("/api/v1/me")
                codes.append(response.status_code)
            # First three pass, the rest are shed.
            assert codes == [200, 200, 200, 429, 429]
            limited = await c.get("/api/v1/tasks")
            assert limited.status_code == 429
            assert limited.headers["Retry-After"]
            assert limited.json()["code"] == "RATE_LIMITED"


async def test_rate_limit_can_be_disabled(engine, tmp_path) -> None:
    import httpx

    settings = Settings(
        app_env="test",
        rate_limit_enabled=False,
        upload_dir=tmp_path,
        llm_provider="mock",
        embedding_provider="mock",
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            codes = []
            for _ in range(6):
                response = await c.get("/api/v1/me")
                codes.append(response.status_code)
            assert all(code == 200 for code in codes)


async def test_health_and_ready_bypass_rate_limit(engine, tmp_path) -> None:
    import httpx

    settings = Settings(
        app_env="test",
        rate_limit_enabled=True,
        rate_limit_per_minute=1,
        upload_dir=tmp_path,
        llm_provider="mock",
        embedding_provider="mock",
    )
    app = create_app(
        settings=settings, engine=engine, session_factory=create_session_factory(engine)
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            # Health stays reachable even after the single permitted request
            # is consumed by /me (which is then limited).
            first = await c.get("/api/v1/me")
            second = await c.get("/health")
            assert second.status_code == 200
            del first
