from collections.abc import AsyncIterator
from datetime import date, time
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from backend.auth.dependencies import SessionLocal
from backend.auth.security import create_access_token
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.session import Session, SessionStatus
from backend.models.user import User, UserRole
from backend.realtime import events


def add_user(email: str, role: UserRole) -> User:
    with SessionLocal() as db:
        user = User(
            email=email,
            full_name=email.split("@")[0],
            password_hash="not-used",
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def add_session(teacher: User, students: list[User]) -> tuple[Session, list[QueueEntry]]:
    with SessionLocal() as db:
        reception = Session(
            teacher_id=teacher.id,
            course_name="Алгоритмы",
            room="Р-123",
            date=date(2026, 9, 8),
            start_time=time(10, 0),
            duration_default=15,
            capacity=1,
            status=SessionStatus.PLANNED,
            frozen=False,
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


def authorization(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def test_publisher_uses_session_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeRedis:
        def publish(self, channel: str, payload: str) -> int:
            calls.append((channel, payload))
            return 2

    monkeypatch.setattr(events, "_publisher", lambda: FakeRedis())
    session_id = uuid4()

    event = events.publish_session_event(session_id, "queue.done")

    assert calls[0][0] == f"session:{session_id}"
    assert event["type"] == "queue.done"
    assert event["session_id"] == str(session_id)
    assert event["event_id"] in calls[0][1]


def test_all_queue_changes_publish_only_after_commit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT)
        for index in range(1, 5)
    ]
    reception, entries = add_session(teacher, students[:3])
    snapshots: list[tuple[str, SessionStatus, bool, dict[UUID, tuple[QueueEntryStatus, int, bool]]]] = []

    def capture(session_id: UUID, event_type: str) -> None:
        with SessionLocal() as db:
            saved_session = db.get(Session, session_id)
            saved_entries = db.scalars(
                select(QueueEntry).where(QueueEntry.session_id == session_id)
            ).all()
            assert saved_session is not None
            snapshots.append(
                (
                    event_type,
                    saved_session.status,
                    saved_session.frozen,
                    {
                        entry.id: (entry.status, entry.position, entry.locked)
                        for entry in saved_entries
                    },
                )
            )

    monkeypatch.setattr("backend.routes.queue.publish_session_event", capture)
    monkeypatch.setattr("backend.routes.sessions.publish_session_event", capture)

    assert client.patch(
        f"/sessions/{reception.id}/queue/reorder",
        headers=authorization(students[2]),
        json={
            "entry_id": str(entries[2].id),
            "target_entry_id": str(entries[0].id),
            "placement": "before",
        },
    ).status_code == 200
    assert client.patch(
        f"/sessions/{reception.id}/queue/{entries[2].id}/lock",
        headers=authorization(students[2]),
        json={"locked": True, "lock_reason": "После пары"},
    ).status_code == 200
    assert client.post(
        f"/students/me/queues/{entries[1].id}/absence",
        headers=authorization(students[1]),
        json={"absence_reason": "Другая встреча"},
    ).status_code == 200
    assert client.post(
        f"/sessions/{reception.id}/freeze", headers=authorization(teacher)
    ).status_code == 200
    assert client.patch(
        f"/sessions/{reception.id}",
        headers=authorization(teacher),
        json={"status": "active"},
    ).status_code == 200
    assert client.post(
        f"/sessions/{reception.id}/queue/{entries[2].id}/done",
        headers=authorization(teacher),
    ).status_code == 200
    assert client.post(
        f"/sessions/{reception.id}/queue/{entries[0].id}/skip",
        headers=authorization(teacher),
    ).status_code == 200
    add_response = client.post(
        f"/sessions/{reception.id}/participants",
        headers=authorization(teacher),
        json={"student_id": str(students[3].id)},
    )
    assert add_response.status_code == 201
    added_entry_id = add_response.json()["entry_id"]
    assert client.delete(
        f"/sessions/{reception.id}/participants/{added_entry_id}",
        headers=authorization(teacher),
    ).status_code == 200

    assert [snapshot[0] for snapshot in snapshots] == [
        "queue.reordered",
        "queue.locked",
        "queue.absent",
        "session.frozen",
        "session.updated",
        "queue.done",
        "queue.skipped",
        "participant.added",
        "participant.removed",
    ]
    assert snapshots[0][3][entries[2].id][1] == 1
    assert snapshots[1][3][entries[2].id][2] is True
    assert snapshots[2][3][entries[1].id][0] == QueueEntryStatus.ABSENT
    assert snapshots[3][2] is True
    assert snapshots[4][1] == SessionStatus.ACTIVE
    assert snapshots[5][3][entries[2].id][0] == QueueEntryStatus.DONE
    assert snapshots[6][3][entries[0].id][0] == QueueEntryStatus.SKIPPED
    assert UUID(added_entry_id) in snapshots[7][3]
    assert UUID(added_entry_id) not in snapshots[8][3]


def test_two_authorized_clients_receive_the_same_event(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    student = add_user("student@example.com", UserRole.STUDENT)
    reception, _ = add_session(teacher, [student])

    async def fake_stream(session_id: UUID) -> AsyncIterator[dict[str, str]]:
        yield {
            "event_id": "ready",
            "type": "realtime.ready",
            "session_id": str(session_id),
            "occurred_at": "2026-09-06T20:00:00Z",
        }
        yield {
            "event_id": "event-1",
            "type": "queue.reordered",
            "session_id": str(session_id),
            "occurred_at": "2026-09-06T20:00:01Z",
        }

    monkeypatch.setattr("backend.routes.ws.stream_session_events", fake_stream)
    teacher_url = (
        f"/ws/sessions/{reception.id}?token={create_access_token(teacher)}"
    )
    student_url = (
        f"/ws/sessions/{reception.id}?token={create_access_token(student)}"
    )

    with client.websocket_connect(teacher_url) as teacher_socket:
        with client.websocket_connect(student_url) as student_socket:
            assert teacher_socket.receive_json()["type"] == "realtime.ready"
            assert student_socket.receive_json()["type"] == "realtime.ready"
            assert teacher_socket.receive_json()["event_id"] == "event-1"
            assert student_socket.receive_json()["event_id"] == "event-1"


def test_outsider_cannot_subscribe(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    participant = add_user("participant@example.com", UserRole.STUDENT)
    outsider = add_user("outsider@example.com", UserRole.STUDENT)
    reception, _ = add_session(teacher, [participant])
    monkeypatch.setattr(
        "backend.routes.ws.stream_session_events",
        lambda _: (_ for _ in ()),
    )

    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(
            f"/ws/sessions/{reception.id}?token={create_access_token(outsider)}"
        ):
            pass

    assert error.value.code == 4403
