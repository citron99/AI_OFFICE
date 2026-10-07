"""Scheduler for the daily process: owner timezone, calendar, retry policy (TZ 14, 8).

The scheduling decision is deterministic and testable; the deployment-level
beat job simply calls the tick endpoint. The scheduler refuses to run until
the owner configures timezone, run time and calendar - exactly as the
integration plan requires.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process_id: str = Field(min_length=1, max_length=80)
    enabled: bool = False  # Off until the owner signs the schedule off.
    timezone: str = Field(min_length=3, max_length=64, default="Europe/Riga")
    run_at: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", default="08:30")
    workdays_only: bool = True
    max_attempts: int = Field(default=1, ge=1, le=3)
    retry_delay_minutes: int = Field(default=30, ge=1, le=720)
    # Fail-closed (TZ 11.2): never compute on a stale 1C snapshot.
    require_fresh_snapshot: bool = True
    snapshot_max_lag_hours: int = Field(default=12, ge=1, le=168)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Unknown timezone: {value}") from error
        return value


class ScheduleDecision(StrEnum):
    DUE = "due"
    NOT_DUE = "not_due"
    DISABLED = "disabled"
    NON_WORKING_DAY = "non_working_day"
    SNAPSHOT_STALE = "snapshot_stale"
    COOLDOWN = "cooldown"


def next_run_at(config: ScheduleConfig, after_utc: datetime) -> datetime:
    """The next scheduled moment strictly after ``after_utc``, in owner time."""

    tz = ZoneInfo(config.timezone)
    hour, minute = (int(part) for part in config.run_at.split(":"))
    local = after_utc.astimezone(tz)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    if config.workdays_only:
        while candidate.weekday() >= 5:  # Saturday=5, Sunday=6
            candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def evaluate(
    config: ScheduleConfig,
    *,
    now_utc: datetime,
    watermark_at: datetime | None = None,
    last_attempt_at: datetime | None = None,
    last_attempt_ok: bool = False,
    attempts_today: int = 0,
) -> tuple[ScheduleDecision, datetime]:
    """Decide whether the process should run right now (deterministic)."""

    tz = ZoneInfo(config.timezone)
    if not config.enabled:
        return ScheduleDecision.DISABLED, next_run_at(config, now_utc)
    local_now = now_utc.astimezone(tz)
    if config.workdays_only and local_now.weekday() >= 5:
        return ScheduleDecision.NON_WORKING_DAY, next_run_at(config, now_utc)

    hour, minute = (int(part) for part in config.run_at.split(":"))
    today_run = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local_now < today_run:
        return ScheduleDecision.NOT_DUE, next_run_at(config, now_utc)

    if (
        last_attempt_at is not None
        and last_attempt_ok
        and last_attempt_at.astimezone(tz).date() == local_now.date()
    ):
        # Already succeeded today: the next run is tomorrow.
        return ScheduleDecision.NOT_DUE, next_run_at(config, now_utc)

    if last_attempt_at is not None and not last_attempt_ok:
        attempted_today = last_attempt_at.astimezone(tz).date() == local_now.date()
        cooldown_end = last_attempt_at + timedelta(minutes=config.retry_delay_minutes)
        if attempted_today and now_utc < cooldown_end:
            return ScheduleDecision.COOLDOWN, cooldown_end.astimezone(UTC)
        if attempted_today and attempts_today >= config.max_attempts:
            # Bounded retries (TZ REL-002): further runs wait for tomorrow.
            return ScheduleDecision.NOT_DUE, next_run_at(config, now_utc)

    if config.require_fresh_snapshot:
        if watermark_at is None:
            return ScheduleDecision.SNAPSHOT_STALE, next_run_at(config, now_utc)
        age = now_utc - watermark_at
        if age > timedelta(hours=config.snapshot_max_lag_hours):
            return ScheduleDecision.SNAPSHOT_STALE, next_run_at(config, now_utc)

    return ScheduleDecision.DUE, now_utc


def describe(config: ScheduleConfig, *, now_utc: datetime) -> dict[str, Any]:
    next_at = next_run_at(config, now_utc)
    return {
        "config": config.model_dump(mode="json"),
        "next_run_at": next_at,
        "local_time": now_utc.astimezone(ZoneInfo(config.timezone)).isoformat(),
    }
