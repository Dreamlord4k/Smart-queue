from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import backend.routes.sessions as session_routes
from backend.auth.dependencies import SessionLocal
from backend.auth.security import create_access_token
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.session import Session, SessionStatus
from backend.models.user import User, UserRole


def authorization(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def add_user(email: str, role: UserRole) -> User:
    with SessionLocal() as db:
        user = User(
            email=email,
            full_name=email.split("@")[0],
            password_hash="not-used-in-session-tests",
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def add_session(
    teacher: User,
    students: list[User],
    *,
    status: SessionStatus = SessionStatus.PLANNED,
    frozen: bool = False,
    capacity: int = 1,
    duration_default: int = 15,
    session_date: date = date(2026, 9, 8),
) -> tuple[Session, list[QueueEntry]]:
    with SessionLocal() as db:
        reception = Session(
            teacher_id=teacher.id,
            course_name="Алгоритмы",
            room="Р-123",
            date=session_date,
            start_time=time(10, 0),
            duration_default=duration_default,
            capacity=capacity,
            status=status,
            frozen=frozen,
        )
        db.add(reception)
        db.flush()
        entries = [
            QueueEntry(
                session_id=reception.id,
                student_id=student.id,
                position=position,
                status=QueueEntryStatus.WAITING,
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


def test_mine_lists_only_current_teachers_sessions(client: TestClient) -> None:
    owner = add_user("owner@example.com", UserRole.TEACHER)
    other = add_user("other@example.com", UserRole.TEACHER)
    add_session(owner, [], status=SessionStatus.ACTIVE)
    add_session(
        owner,
        [],
        status=SessionStatus.PLANNED,
        session_date=date(2026, 9, 9),
    )
    add_session(
        owner,
        [],
        status=SessionStatus.CLOSED,
        session_date=date(2026, 9, 10),
    )
    add_session(other, [], status=SessionStatus.PLANNED)

    response = client.get("/sessions/mine", headers=authorization(owner))

    assert response.status_code == 200
    assert {item["teacher_id"] for item in response.json()} == {str(owner.id)}
    assert [item["status"] for item in response.json()] == [
        "active",
        "planned",
        "closed",
    ]


def test_only_owner_teacher_changes_session_and_participants(
    client: TestClient,
) -> None:
    owner = add_user("owner@example.com", UserRole.TEACHER)
    other = add_user("other@example.com", UserRole.TEACHER)
    student = add_user("student@example.com", UserRole.STUDENT)
    candidate = add_user("candidate@example.com", UserRole.STUDENT)
    reception, entries = add_session(owner, [student])

    patch_url = f"/sessions/{reception.id}"
    add_url = f"/sessions/{reception.id}/participants"
    delete_url = f"{add_url}/{entries[0].id}"
    assert client.patch(
        patch_url,
        headers=authorization(other),
        json={"duration_default": 20},
    ).status_code == 403
    assert client.patch(
        patch_url,
        headers=authorization(student),
        json={"duration_default": 20},
    ).status_code == 403
    assert client.post(
        add_url,
        headers=authorization(other),
        json={"student_id": str(candidate.id)},
    ).status_code == 403
    assert client.delete(delete_url, headers=authorization(other)).status_code == 403

    with SessionLocal() as db:
        assert db.get(Session, reception.id).duration_default == 15
        assert db.scalar(select(func.count()).select_from(QueueEntry)) == 1


def test_status_transitions_require_freeze_and_start_capacity_channels(
    client: TestClient,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT)
        for index in range(1, 4)
    ]
    reception, entries = add_session(teacher, students, capacity=2)
    url = f"/sessions/{reception.id}"

    unfrozen = client.patch(
        url, headers=authorization(teacher), json={"status": "active"}
    )
    assert unfrozen.status_code == 409
    assert client.post(
        f"{url}/freeze", headers=authorization(teacher)
    ).status_code == 200

    started = client.patch(
        url,
        headers=authorization(teacher),
        json={"status": "active", "duration_default": 20},
    )
    assert started.status_code == 200
    assert started.json()["duration_default"] == 20
    with SessionLocal() as db:
        saved = [db.get(QueueEntry, entry.id) for entry in entries]
        assert [entry.status for entry in saved] == [
            QueueEntryStatus.CALLED,
            QueueEntryStatus.CALLED,
            QueueEntryStatus.WAITING,
        ]
        assert [entry.channel for entry in saved[:2]] == [1, 2]
        assert all(entry.called_at is not None for entry in saved[:2])

    assert client.patch(
        url, headers=authorization(teacher), json={"status": "paused"}
    ).status_code == 200
    assert client.patch(
        url, headers=authorization(teacher), json={"status": "active"}
    ).status_code == 200
    assert client.patch(
        url, headers=authorization(teacher), json={"status": "closed"}
    ).status_code == 200
    assert client.patch(
        url, headers=authorization(teacher), json={"status": "active"}
    ).status_code == 409


def test_add_running_participant_to_end_with_eta_and_reject_duplicate(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    current = add_user("current@example.com", UserRole.STUDENT)
    waiting = add_user("waiting@example.com", UserRole.STUDENT)
    candidate = add_user("candidate@example.com", UserRole.STUDENT)
    reception, entries = add_session(
        teacher,
        [current, waiting],
        status=SessionStatus.ACTIVE,
        frozen=True,
    )
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        called = db.get(QueueEntry, entries[0].id)
        called.status = QueueEntryStatus.CALLED
        called.channel = 1
        called.called_at = now
        db.commit()
    url = f"/sessions/{reception.id}/participants"
    published: list[tuple[object, str]] = []
    monkeypatch.setattr(
        session_routes,
        "publish_session_event",
        lambda session_id, event: published.append((session_id, event)),
    )

    response = client.post(
        url,
        headers=authorization(teacher),
        json={"student_id": str(candidate.id)},
    )

    assert response.status_code == 201
    active_queue = response.json()["active_queue"]
    added = active_queue[-1]
    assert added["student_id"] == str(candidate.id)
    assert added["position"] == 3
    assert added["eta_start"] is not None
    assert [item["position"] for item in active_queue] == [1, 2, 3]
    windows = [
        (datetime.fromisoformat(item["eta_start"]), datetime.fromisoformat(item["eta_end"]))
        for item in active_queue
        if item["eta_start"] is not None and item["eta_end"] is not None
    ]
    assert all(end <= next_start for (_, end), (next_start, _) in zip(windows, windows[1:]))
    assert published == [(reception.id, "participant.added")]
    duplicate = client.post(
        url,
        headers=authorization(teacher),
        json={"student_id": str(candidate.id)},
    )
    assert duplicate.status_code == 409
    with SessionLocal() as db:
        count = db.scalar(
            select(func.count())
            .select_from(QueueEntry)
            .where(
                QueueEntry.session_id == reception.id,
                QueueEntry.student_id == candidate.id,
            )
        )
        assert count == 1


def test_delete_waiting_normalizes_queue_but_preserves_history(
    client: TestClient,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT)
        for index in range(1, 4)
    ]
    reception, entries = add_session(teacher, students)
    with SessionLocal() as db:
        historical = db.get(QueueEntry, entries[0].id)
        historical.status = QueueEntryStatus.DONE
        db.commit()

    base_url = f"/sessions/{reception.id}/participants"
    historical_response = client.delete(
        f"{base_url}/{entries[0].id}", headers=authorization(teacher)
    )
    deleted = client.delete(
        f"{base_url}/{entries[1].id}", headers=authorization(teacher)
    )

    assert historical_response.status_code == 409
    assert deleted.status_code == 200
    assert [item["position"] for item in deleted.json()["active_queue"]] == [1]
    with SessionLocal() as db:
        assert db.get(QueueEntry, entries[0].id) is not None
        assert db.get(QueueEntry, entries[1].id) is None
        assert db.get(QueueEntry, entries[2].id).position == 1


def test_close_returns_reconstructed_report(client: TestClient) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT)
        for index in range(1, 4)
    ]
    reception, entries = add_session(
        teacher,
        students,
        status=SessionStatus.ACTIVE,
        frozen=True,
        capacity=2,
        duration_default=10,
    )
    started = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
    with SessionLocal() as db:
        first = db.get(QueueEntry, entries[0].id)
        first.status = QueueEntryStatus.DONE
        first.called_at = started
        first.finished_at = started + timedelta(minutes=8)
        second = db.get(QueueEntry, entries[1].id)
        second.status = QueueEntryStatus.DONE
        second.called_at = started + timedelta(minutes=8)
        second.finished_at = started + timedelta(minutes=20)
        third = db.get(QueueEntry, entries[2].id)
        third.status = QueueEntryStatus.SKIPPED
        db.commit()

    response = client.patch(
        f"/sessions/{reception.id}",
        headers=authorization(teacher),
        json={"status": "closed"},
    )

    assert response.status_code == 200
    report = response.json()["report"]
    assert report["accepted_count"] == 2
    assert report["skipped_count"] == 1
    assert report["average_service_seconds"] == pytest.approx(600)
    assert report["planned_duration_seconds"] == 1200
    assert report["actual_duration_seconds"] == 1200
    assert report["average_eta_error_seconds"] == pytest.approx(180)
