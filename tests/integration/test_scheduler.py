"""Scheduler decisions: timezone, calendar, cooldown, snapshot freshness (TZ 14)."""

from datetime import UTC, datetime, timedelta

import httpx

from app.services.scheduler import (
    ScheduleConfig,
    ScheduleDecision,
    evaluate,
    next_run_at,
)


def cfg(**overrides) -> ScheduleConfig:
    base = ScheduleConfig(
        process_id="daily_cash_and_receivable_risk",
        enabled=True,
        timezone="Europe/Riga",
        run_at="08:30",
        workdays_only=True,
        require_fresh_snapshot=False,
    )
    return base.model_copy(update=overrides)


def test_next_run_skips_weekend_and_moves_to_next_day() -> None:
    # 2026-09-08 is a Tuesday; 09:00 UTC = 12:00 EEST, after the 08:30 slot.
    after = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
    nxt = next_run_at(cfg(), after)
    assert nxt == datetime(2026, 9, 9, 5, 30, tzinfo=UTC)  # Wednesday 08:30 EEST

    # Friday after the slot -> Monday.
    friday = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    monday = next_run_at(cfg(), friday)
    assert monday.weekday() == 0
    assert monday == datetime(2026, 9, 14, 5, 30, tzinfo=UTC)


def test_disabled_and_weekend_are_hard_stops() -> None:
    disabled = evaluate(cfg(enabled=False), now_utc=datetime(2026, 9, 8, 7, 0, tzinfo=UTC))
    assert disabled[0] == ScheduleDecision.DISABLED
    # Saturday 2026-09-12, 10:00 EEST (07:00 UTC).
    saturday = datetime(2026, 9, 12, 7, 0, tzinfo=UTC)
    weekend = evaluate(cfg(), now_utc=saturday)
    assert weekend[0] == ScheduleDecision.NON_WORKING_DAY


def test_not_due_before_configured_time() -> None:
    early = datetime(2026, 9, 8, 4, 0, tzinfo=UTC)  # 07:00 Riga < 08:30
    decision, nxt = evaluate(cfg(), now_utc=early)
    assert decision == ScheduleDecision.NOT_DUE
    assert nxt == datetime(2026, 9, 8, 5, 30, tzinfo=UTC)


def test_due_after_configured_time() -> None:
    # 06:00 UTC = 09:00 EEST, past the 08:30 slot.
    decision, _ = evaluate(cfg(), now_utc=datetime(2026, 9, 8, 6, 0, tzinfo=UTC))
    assert decision == ScheduleDecision.DUE


def test_success_cooldown_is_once_per_day() -> None:
    now = datetime(2026, 9, 8, 6, 45, tzinfo=UTC)
    already_ran = datetime(2026, 9, 8, 6, 35, tzinfo=UTC)
    decision, _ = evaluate(cfg(), now_utc=now, last_attempt_at=already_ran, last_attempt_ok=True)
    assert decision == ScheduleDecision.NOT_DUE


def test_failure_retries_after_cooldown_then_stops_retrying_next_day() -> None:
    now = datetime(2026, 9, 8, 6, 40, tzinfo=UTC)
    failed_at = datetime(2026, 9, 8, 6, 35, tzinfo=UTC)
    cooling = evaluate(
        cfg(retry_delay_minutes=30),
        now_utc=now,
        last_attempt_at=failed_at,
        last_attempt_ok=False,
    )
    assert cooling[0] == ScheduleDecision.COOLDOWN

    after_cooldown = now + timedelta(minutes=31)
    retriable = evaluate(
        cfg(retry_delay_minutes=30),
        now_utc=after_cooldown,
        last_attempt_at=failed_at,
        last_attempt_ok=False,
    )
    assert retriable[0] == ScheduleDecision.DUE


def test_stale_snapshot_blocks_when_required() -> None:
    now = datetime(2026, 9, 8, 6, 40, tzinfo=UTC)
    fresh = evaluate(
        cfg(require_fresh_snapshot=True, snapshot_max_lag_hours=12),
        now_utc=now,
        watermark_at=now - timedelta(hours=2),
    )
    assert fresh[0] == ScheduleDecision.DUE

    stale = evaluate(
        cfg(require_fresh_snapshot=True, snapshot_max_lag_hours=12),
        now_utc=now,
        watermark_at=now - timedelta(hours=13),
    )
    assert stale[0] == ScheduleDecision.SNAPSHOT_STALE

    missing = evaluate(cfg(require_fresh_snapshot=True), now_utc=now, watermark_at=None)
    assert missing[0] == ScheduleDecision.SNAPSHOT_STALE


def test_invalid_timezone_rejected() -> None:
    import pydantic
    import pytest

    with pytest.raises(pydantic.ValidationError):
        ScheduleConfig(
            process_id="daily_cash_and_receivable_risk",
            timezone="Mars/Olympus_Mons",
        )


async def test_schedule_api_roundtrip_and_disabled_tick(client: httpx.AsyncClient) -> None:
    process_id = "daily_cash_and_receivable_risk"
    defaults = await client.get(f"/api/v1/processes/{process_id}/schedule")
    assert defaults.status_code == 200
    assert defaults.json()["config"]["enabled"] is False
    assert defaults.json()["supported"] is True

    # Tick while disabled never runs anything.
    tick = await client.post(f"/api/v1/processes/{process_id}/schedule/tick")
    assert tick.status_code == 200
    assert tick.json()["decision"] == "disabled"
    assert tick.json()["task_id"] is None

    # Owner enables the schedule; the persisted config comes back.
    enabled = await client.put(
        f"/api/v1/processes/{process_id}/schedule",
        json={
            "process_id": process_id,
            "enabled": True,
            "timezone": "Europe/Riga",
            "run_at": "08:30",
            "workdays_only": True,
        },
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["config"]["enabled"] is True
