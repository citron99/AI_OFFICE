"""The Celery worker builds its app, engine and providers once per process."""

import types
from typing import Any

from app import jobs


def test_worker_runtime_is_built_once_reused_and_closed(monkeypatch) -> None:
    events: list[str] = []

    class FakeLifespan:
        async def __aenter__(self) -> None:
            events.append("enter")

        async def __aexit__(self, *exc: object) -> None:
            events.append("exit")

    class FakeApp:
        router = types.SimpleNamespace(lifespan_context=lambda app: FakeLifespan())

    def fake_create_app(*, settings: Any) -> FakeApp:
        events.append("create")
        return FakeApp()

    monkeypatch.setattr(jobs, "create_app", fake_create_app)
    monkeypatch.setattr(jobs, "_worker_runtime", None)
    try:
        first = jobs._get_worker_runtime()
        second = jobs._get_worker_runtime()
        assert first is second
        assert events == ["create", "enter"]

        async def answer() -> int:
            return 42

        assert jobs._drive(first.loop, answer()) == 42

        seen: list[tuple[str, Any]] = []

        async def fake_execute(task_id: str, app: Any) -> None:
            seen.append((task_id, app))

        monkeypatch.setattr(jobs, "_execute_stored_task", fake_execute)
        jobs.process_task("tsk_worker")
        assert seen == [("tsk_worker", first.app)]
        assert events == ["create", "enter"]
    finally:
        jobs._close_worker_runtime()
    assert events == ["create", "enter", "exit"]
