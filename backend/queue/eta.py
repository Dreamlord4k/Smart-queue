from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.session import Session, SessionStatus


ACTIVE_STATUSES = (QueueEntryStatus.WAITING, QueueEntryStatus.CALLED)


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
) -> dict[UUID, tuple[datetime, datetime]]:
    """Рассчитывает интервалы ETA из текущего состояния активной очереди."""
    current_time = now or datetime.now(timezone.utc)
    service_time = timedelta(minutes=reception.duration_default)
    active_entries = sorted(entries, key=lambda entry: entry.position)

    if reception.status == SessionStatus.PLANNED:
        session_start = datetime.combine(
            reception.date, reception.start_time, tzinfo=timezone.utc
        )
        return {
            entry.id: (
                session_start + service_time * index,
                session_start + service_time * (index + 1),
            )
            for index, entry in enumerate(active_entries)
        }

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
        finishes_at = starts_at + service_time
        result[entry.id] = (starts_at, finishes_at)
        channel_free_at[channel_index] = finishes_at

    return result
