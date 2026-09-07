from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.auth.dependencies import SessionLocal
from backend.auth.security import create_access_token
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.service_stat import ServiceStat
from backend.models.session import Session, SessionStatus
from backend.models.user import User, UserRole


def authorization(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def add_user(email: str, role: UserRole) -> User:
    with SessionLocal() as db:
        user = User(
            email=email,
            full_name=email.split("@")[0],
            password_hash="not-used-in-queue-tests",
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def add_active_session(
    teacher: User,
    students: list[User],
    *,
    capacity: int = 1,
    called_count: int = 1,
) -> tuple[Session, list[QueueEntry]]:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        reception = Session(
            teacher_id=teacher.id,
            course_name="Алгоритмы",
            room="Р-123",
            date=date(2026, 9, 8),
            start_time=time(10, 0),
            duration_default=15,
            capacity=capacity,
            status=SessionStatus.ACTIVE,
            frozen=True,
        )
        db.add(reception)
        db.flush()
        entries = [
            QueueEntry(
                session_id=reception.id,
                student_id=student.id,
                position=position,
                status=(
                    QueueEntryStatus.CALLED
                    if position <= called_count
                    else QueueEntryStatus.WAITING
                ),
                channel=position if position <= called_count else None,
                called_at=now - timedelta(minutes=10)
                if position <= called_count
                else None,
            )
            for position, student in enumerate(students, start=1)
        ]
        db.add_all(entries)
        db.commit()
        db.refresh(reception)
        for entry in entries:
            db.refresh(entry)
            db.expunge(entry)
        db.expunge(reception)
        return reception, entries


def test_done_updates_ema_and_calls_next_in_same_channel(
    client: TestClient,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT)
        for index in range(1, 4)
    ]
    reception, entries = add_active_session(teacher, students)

    first_response = client.post(
        f"/sessions/{reception.id}/queue/{entries[0].id}/done",
        headers=authorization(teacher),
    )

    assert first_response.status_code == 200
    first_body = first_response.json()
    assert first_body["status"] == "done"
    assert first_body["released_channel"] == 1
    assert first_body["next_entry_id"] == str(entries[1].id)
    assert first_body["n_observations"] == 1
    assert first_body["ema_estimate"] == pytest.approx(600, abs=5)
    assert first_body["variance"] == 0

    with SessionLocal() as db:
        second = db.get(QueueEntry, entries[1].id)
        second.called_at = datetime.now(timezone.utc) - timedelta(minutes=15)
        db.commit()

    second_response = client.post(
        f"/sessions/{reception.id}/queue/{entries[1].id}/done",
        headers=authorization(teacher),
    )

    assert second_response.status_code == 200
    second_body = second_response.json()
    assert second_body["next_entry_id"] == str(entries[2].id)
    assert second_body["n_observations"] == 2
    assert second_body["ema_estimate"] == pytest.approx(690, abs=5)
    assert second_body["variance"] == pytest.approx(18_900, abs=1_000)


def test_skip_does_not_change_service_stat_and_calls_next(
    client: TestClient,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT)
        for index in range(1, 3)
    ]
    reception, entries = add_active_session(teacher, students)

    response = client.post(
        f"/sessions/{reception.id}/queue/{entries[0].id}/skip",
        headers=authorization(teacher),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert response.json()["n_observations"] == 0
    assert response.json()["next_entry_id"] == str(entries[1].id)
    with SessionLocal() as db:
        skipped = db.get(QueueEntry, entries[0].id)
        called = db.get(QueueEntry, entries[1].id)
        assert skipped.finished_at is None
        assert called.status == QueueEntryStatus.CALLED
        assert called.channel == 1
        assert db.get(ServiceStat, reception.id) is None


def test_only_owner_teacher_can_finish_current(client: TestClient) -> None:
    owner = add_user("owner@example.com", UserRole.TEACHER)
    other_teacher = add_user("other@example.com", UserRole.TEACHER)
    student = add_user("student@example.com", UserRole.STUDENT)
    reception, entries = add_active_session(owner, [student])
    url = f"/sessions/{reception.id}/queue/{entries[0].id}/done"

    assert client.post(url, headers=authorization(student)).status_code == 403
    assert client.post(url, headers=authorization(other_teacher)).status_code == 403
    with SessionLocal() as db:
        assert db.get(QueueEntry, entries[0].id).status == QueueEntryStatus.CALLED


def test_queue_state_exposes_current_channel_to_teacher(
    client: TestClient,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    student = add_user("student@example.com", UserRole.STUDENT)
    reception, _ = add_active_session(teacher, [student])

    response = client.get(
        f"/sessions/{reception.id}/queue", headers=authorization(teacher)
    )

    assert response.status_code == 200
    assert response.json()["entries"][0]["channel"] == 1
    assert response.json()["entries"][0]["called_at"] is not None


def test_done_rejects_called_entry_outside_active_session(
    client: TestClient,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    student = add_user("student@example.com", UserRole.STUDENT)
    reception, entries = add_active_session(teacher, [student])
    with SessionLocal() as db:
        saved_session = db.get(Session, reception.id)
        saved_session.status = SessionStatus.PAUSED
        db.commit()

    response = client.post(
        f"/sessions/{reception.id}/queue/{entries[0].id}/done",
        headers=authorization(teacher),
    )

    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.get(QueueEntry, entries[0].id).status == QueueEntryStatus.CALLED
        assert db.get(ServiceStat, reception.id) is None


def test_absence_of_called_entry_releases_its_channel(client: TestClient) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    current = add_user("current@example.com", UserRole.STUDENT)
    next_student = add_user("next@example.com", UserRole.STUDENT)
    reception, entries = add_active_session(teacher, [current, next_student])

    response = client.post(
        f"/students/me/queues/{entries[0].id}/absence",
        headers=authorization(current),
        json={"absence_reason": "Не успеваю"},
    )

    assert response.status_code == 200
    with SessionLocal() as db:
        absent = db.get(QueueEntry, entries[0].id)
        called = db.get(QueueEntry, entries[1].id)
        assert absent.status == QueueEntryStatus.ABSENT
        assert absent.channel is None
        assert called.status == QueueEntryStatus.CALLED
        assert called.channel == 1


def test_repeated_concurrent_done_advances_channel_once(client: TestClient) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT)
        for index in range(1, 4)
    ]
    reception, entries = add_active_session(teacher, students)
    url = f"/sessions/{reception.id}/queue/{entries[0].id}/done"
    headers = authorization(teacher)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(lambda _: client.post(url, headers=headers), range(2))
        )

    assert sorted(response.status_code for response in responses) == [200, 409]
    with SessionLocal() as db:
        queue = list(
            db.scalars(
                select(QueueEntry)
                .where(QueueEntry.session_id == reception.id)
                .order_by(QueueEntry.position)
            ).all()
        )
        assert [entry.status for entry in queue] == [
            QueueEntryStatus.DONE,
            QueueEntryStatus.CALLED,
            QueueEntryStatus.WAITING,
        ]
        assert [entry.position for entry in queue[1:]] == [1, 2]
        assert db.get(ServiceStat, reception.id).n_observations == 1
