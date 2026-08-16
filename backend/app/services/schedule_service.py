from __future__ import annotations

import random
from datetime import datetime, time, timedelta

DEFAULT_SCHEDULE_WINDOW = "06:00-08:00"


def normalize_schedule_window(window: str | None) -> str:
    if not window:
        return DEFAULT_SCHEDULE_WINDOW

    raw = window.strip()
    try:
        start_raw, end_raw = raw.split("-", 1)
        start = datetime.strptime(start_raw.strip(), "%H:%M").time()
        end = datetime.strptime(end_raw.strip(), "%H:%M").time()
    except ValueError:
        return DEFAULT_SCHEDULE_WINDOW

    return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"


def validate_schedule_window(window: str) -> str:
    raw = window.strip()
    try:
        start_raw, end_raw = raw.split("-", 1)
        start = datetime.strptime(start_raw.strip(), "%H:%M").time()
        end = datetime.strptime(end_raw.strip(), "%H:%M").time()
    except ValueError as exc:
        raise ValueError("时间段格式应为 HH:MM-HH:MM，例如 06:00-08:00。") from exc

    if start == end:
        raise ValueError("开始时间和结束时间不能相同。")

    return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"


def sanitize_frequency_days(value: int | None) -> int:
    return max(1, int(value or 1))


def sanitize_cooldown_minutes(value: int | None) -> int:
    return max(0, int(value or 0))


def sanitize_retry_limit(value: int | None) -> int:
    return max(0, int(value or 0))


def sanitize_retry_cooldown_minutes(value: int | None) -> int:
    return max(1, int(value or 30))


def get_local_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=8)


def compute_next_run_at(window: str | None, now: datetime | None = None) -> datetime:
    normalized = normalize_schedule_window(window)
    current = now or get_local_now()
    start_time, end_time = _parse_window(normalized)

    today_start = datetime.combine(current.date(), start_time)
    today_end = datetime.combine(current.date(), end_time)
    if today_end <= today_start:
        today_end += timedelta(days=1)

    if current < today_end:
        candidate_start = max(today_start, current)
        if candidate_start < today_end:
            return _random_between(candidate_start, today_end)

    next_start = today_start + timedelta(days=1)
    next_end = today_end + timedelta(days=1)
    return _random_between(next_start, next_end)


def compute_friend_next_run_at(
    *,
    schedule_window: str | None,
    now: datetime | None = None,
    frequency_days: int | None = None,
    cooldown_minutes: int | None = None,
    last_run_at: datetime | None = None,
) -> datetime:
    current = now or get_local_now()
    base_time = current
    if last_run_at is not None:
        next_allowed_date = last_run_at.date() + timedelta(days=sanitize_frequency_days(frequency_days))
        base_time = max(base_time, datetime.combine(next_allowed_date, time.min))
        base_time = max(base_time, last_run_at + timedelta(minutes=sanitize_cooldown_minutes(cooldown_minutes)))
    return compute_next_run_at(schedule_window, now=base_time)


def compute_retry_run_at(
    *,
    now: datetime | None = None,
    retry_cooldown_minutes: int | None = None,
) -> datetime:
    current = now or get_local_now()
    return current + timedelta(minutes=sanitize_retry_cooldown_minutes(retry_cooldown_minutes))


def _parse_window(window: str) -> tuple[time, time]:
    start_raw, end_raw = window.split("-", 1)
    start = datetime.strptime(start_raw, "%H:%M").time()
    end = datetime.strptime(end_raw, "%H:%M").time()
    return start, end


def _random_between(start: datetime, end: datetime) -> datetime:
    seconds = int((end - start).total_seconds())
    if seconds <= 0:
        return start
    return start + timedelta(seconds=random.randint(0, seconds))
