from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest

from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.session import Session, SessionStatus
from backend.queue.eta import calculate_eta_ranges, update_ema


def test_update_ema_uses_first_observation_then_alpha_point_three() -> None:
    first_ema, first_variance = update_ema(None, 0.0, 600.0)
    second_ema, second_variance = update_ema(first_ema, first_variance, 900.0)

    assert first_ema == 600.0
    assert first_variance == 0.0
    assert second_ema == 690.0
    assert second_variance == 18_900.0


def test_eta_greedily_uses_earliest_of_two_channels() -> None:
    now = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    reception = Session(
        id=uuid4(),
        teacher_id=uuid4(),
        course_name="Алгоритмы",
        room="Р-123",
        date=date(2026, 9, 8),
        start_time=time(10, 0),
        duration_default=15,
        capacity=2,
        status=SessionStatus.ACTIVE,
        frozen=True,
    )
    called_first = QueueEntry(
        id=uuid4(),
        session_id=reception.id,
        student_id=uuid4(),
        position=1,
        status=QueueEntryStatus.CALLED,
        channel=1,
        called_at=now - timedelta(seconds=200),
    )
    called_second = QueueEntry(
        id=uuid4(),
        session_id=reception.id,
        student_id=uuid4(),
        position=2,
        status=QueueEntryStatus.CALLED,
        channel=2,
        called_at=now - timedelta(seconds=500),
    )
    waiting_first = QueueEntry(
        id=uuid4(),
        session_id=reception.id,
        student_id=uuid4(),
        position=3,
        status=QueueEntryStatus.WAITING,
    )
    waiting_second = QueueEntry(
        id=uuid4(),
        session_id=reception.id,
        student_id=uuid4(),
        position=4,
        status=QueueEntryStatus.WAITING,
    )

    result = calculate_eta_ranges(
        reception,
        [called_first, called_second, waiting_first, waiting_second],
        now=now,
        ema_estimate=600.0,
        variance=1.0,
    )

    assert result[waiting_first.id] == (
        now + timedelta(seconds=99),
        now + timedelta(seconds=101),
    )
    assert result[waiting_second.id] == (
        now + timedelta(seconds=399),
        now + timedelta(seconds=401),
    )


def test_eta_range_uses_variance() -> None:
    now = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    reception = Session(
        id=uuid4(),
        teacher_id=uuid4(),
        course_name="Алгоритмы",
        room="Р-123",
        date=date(2026, 9, 8),
        start_time=time(10, 0),
        duration_default=15,
        capacity=1,
        status=SessionStatus.ACTIVE,
        frozen=True,
    )
    current = QueueEntry(
        id=uuid4(),
        session_id=reception.id,
        student_id=uuid4(),
        position=1,
        status=QueueEntryStatus.CALLED,
        channel=1,
        called_at=now,
    )
    waiting = QueueEntry(
        id=uuid4(),
        session_id=reception.id,
        student_id=uuid4(),
        position=2,
        status=QueueEntryStatus.WAITING,
    )

    result = calculate_eta_ranges(
        reception,
        [current, waiting],
        now=now,
        ema_estimate=600.0,
        variance=10_000.0,
    )

    assert result[waiting.id] == (
        now + timedelta(seconds=500),
        now + timedelta(seconds=700),
    )


def test_free_channels_share_start_but_keep_non_zero_range_without_stats() -> None:
    now = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    reception = Session(
        id=uuid4(),
        teacher_id=uuid4(),
        course_name="Алгоритмы",
        room="Р-123",
        date=date(2026, 9, 8),
        start_time=time(10, 0),
        duration_default=15,
        capacity=10,
        status=SessionStatus.ACTIVE,
        frozen=True,
    )
    waiting = [
        QueueEntry(
            id=uuid4(),
            session_id=reception.id,
            student_id=uuid4(),
            position=position,
            status=QueueEntryStatus.WAITING,
        )
        for position in range(1, 5)
    ]

    result = calculate_eta_ranges(
        reception,
        waiting,
        now=now,
        ema_estimate=None,
        variance=0.0,
    )

    assert {result[entry.id][0] for entry in waiting} == {now}
    assert {result[entry.id][1] for entry in waiting} == {
        now + timedelta(minutes=reception.duration_default)
    }


@pytest.mark.parametrize("real_time", [-1.0])
def test_update_ema_rejects_negative_time(real_time: float) -> None:
    with pytest.raises(ValueError):
        update_ema(600.0, 0.0, real_time)
