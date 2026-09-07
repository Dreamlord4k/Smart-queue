from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from backend.config import EMA_ALPHA
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.session import Session, SessionStatus


ACTIVE_STATUSES = (QueueEntryStatus.WAITING, QueueEntryStatus.CALLED)
UNIVERSITY_TIME_ZONE = ZoneInfo("Asia/Yekaterinburg")


def update_ema(
    previous_ema: float | None,
    previous_variance: float,
    real_time: float,
    *,
    alpha: float = EMA_ALPHA,
) -> tuple[float, float]:
    """Возвращает обновлённые EMA и экспоненциальную дисперсию в секундах."""
    if real_time < 0:
        raise ValueError("Фактическое время не может быть отрицательным")
    if not 0 < alpha <= 1:
        raise ValueError("Коэффициент EMA должен быть в диапазоне (0, 1]")
    if previous_ema is None:
        return real_time, 0.0

    delta = real_time - previous_ema
    ema_estimate = alpha * real_time + (1 - alpha) * previous_ema
    variance = (1 - alpha) * (max(previous_variance, 0.0) + alpha * delta**2)
    return ema_estimate, variance


def normalize_active_positions(entries: list[QueueEntry]) -> list[QueueEntry]:
    """Убирает разрывы только в активной очереди, сохраняя историю выбывших."""
    active_entries = sorted(
        (entry for entry in entries if entry.status in ACTIVE_STATUSES),
        key=lambda entry: (entry.position, entry.created_at, entry.id),
    )
    for position, entry in enumerate(active_entries, start=1):
        entry.position = position
    return active_entries


def calculate_eta_ranges(
    reception: Session,
    entries: list[QueueEntry],
    *,
    now: datetime | None = None,
    ema_estimate: float | None = None,
    variance: float = 0.0,
) -> dict[UUID, tuple[datetime, datetime]]:
    """Рассчитывает интервалы ETA из текущего состояния активной очереди."""
    current_time = now or datetime.now(timezone.utc)
    active_entries = sorted(entries, key=lambda entry: entry.position)

    if reception.status == SessionStatus.PLANNED:
        service_time = timedelta(minutes=reception.duration_default)
        session_start = datetime.combine(
            reception.date, reception.start_time, tzinfo=UNIVERSITY_TIME_ZONE
        )
        return {
            entry.id: (
                session_start + service_time * index,
                session_start + service_time * (index + 1),
            )
            for index, entry in enumerate(active_entries)
        }

    service_seconds = (
        ema_estimate
        if ema_estimate is not None
        else float(reception.duration_default * 60)
    )
    service_time = timedelta(seconds=max(service_seconds, 0.0))
    channel_free_at = [current_time for _ in range(reception.capacity)]
    result: dict[UUID, tuple[datetime, datetime]] = {}

    for entry in (item for item in active_entries if item.status == QueueEntryStatus.CALLED):
        channel_index = (entry.channel or 1) - 1
        if channel_index >= reception.capacity:
            continue
        started_at = entry.called_at or current_time
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        finishes_at = max(current_time, started_at + service_time)
        channel_free_at[channel_index] = finishes_at
        result[entry.id] = (current_time, finishes_at)

    for entry in (item for item in active_entries if item.status == QueueEntryStatus.WAITING):
        channel_index = min(
            range(reception.capacity), key=lambda index: channel_free_at[index]
        )
        starts_at = channel_free_at[channel_index]
        result[entry.id] = (
            starts_at,
            starts_at + service_time,
        )
        channel_free_at[channel_index] = starts_at + service_time

    return result
