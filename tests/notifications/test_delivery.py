from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.auth.dependencies import SessionLocal
from backend.auth.security import create_access_token
from backend.models.notification_log import (
    NotificationLog,
    NotificationStatus,
    NotificationType,
)
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.session import Session, SessionStatus
from backend.models.user import User, UserRole
from backend.notifications.service import (
    process_queue_event,
    retry_failed_notifications,
    run_soft_notifications,
)


class FakeTransport:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.sent: list[tuple[int, str]] = []

    def send(self, telegram_id: int, message: str) -> None:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("telegram unavailable")
        self.sent.append((telegram_id, message))


def add_user(email: str, role: UserRole, telegram_id: int | None = None) -> User:
    with SessionLocal() as db:
        user = User(
            email=email,
            full_name=email.split("@")[0],
            password_hash="not-used",
            role=role,
            telegram_id=telegram_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def add_active_session(
    teacher: User, students: list[User]
) -> tuple[Session, list[QueueEntry]]:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        reception = Session(
            teacher_id=teacher.id,
            course_name="Алгоритмы",
            room="Р-123",
            date=date(2026, 9, 8),
            start_time=time(10),
            duration_default=15,
            capacity=1,
            status=SessionStatus.ACTIVE,
            frozen=True,
        )
        db.add(reception)
        db.flush()
        entries = [
            QueueEntry(
                session_id=reception.id,
                student_id=student.id,
                position=index,
                status=(
                    QueueEntryStatus.CALLED
                    if index == 1
                    else QueueEntryStatus.WAITING
                ),
                channel=1 if index == 1 else None,
                called_at=now - timedelta(minutes=10) if index == 1 else None,
            )
            for index, student in enumerate(students, start=1)
        ]
        db.add_all(entries)
        db.commit()
        db.refresh(reception)
        db.expunge(reception)
        for entry in entries:
            db.refresh(entry)
            db.expunge(entry)
        return reception, entries


def authorization(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def test_soft_buffer_and_hard_call_are_deduplicated_after_done(
    client: TestClient, monkeypatch
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT, 1000 + index)
        for index in range(1, 4)
    ]
    reception, entries = add_active_session(teacher, students)
    transport = FakeTransport()
    initial_event = {
        "event_id": "start-event",
        "type": "session.updated",
        "session_id": str(reception.id),
    }

    with SessionLocal() as db:
        run_soft_notifications(db, transport)
        process_queue_event(db, initial_event, transport)
        sent_before_repeat = len(transport.sent)
        process_queue_event(db, initial_event, transport)
    assert len(transport.sent) == sent_before_repeat

    published: list[dict[str, str]] = []
    monkeypatch.setattr(
        "backend.routes.queue.publish_session_event",
        lambda session_id, event_type: published.append(
            {"event_id": "done-event", "type": event_type, "session_id": str(session_id)}
        ),
    )
    response = client.post(
        f"/sessions/{reception.id}/queue/{entries[0].id}/done",
        headers=authorization(teacher),
    )
    assert response.status_code == 200
    with SessionLocal() as db:
        process_queue_event(db, published[0], transport)
        logs = list(db.scalars(select(NotificationLog)).all())

    assert {log.type for log in logs} == {
        NotificationType.SOFT,
        NotificationType.BUFFER,
        NotificationType.HARD_CALL,
    }
    assert len({(log.event_key, log.recipient_id) for log in logs}) == len(logs)
    assert any(
        log.type == NotificationType.HARD_CALL
        and log.queue_entry_id == entries[1].id
        for log in logs
    )
    assert any(
        log.type == NotificationType.BUFFER
        and log.queue_entry_id == entries[2].id
        for log in logs
    )


def test_transport_error_does_not_rollback_queue_and_can_retry(
    client: TestClient, monkeypatch
) -> None:
    teacher = add_user("owner@example.com", UserRole.TEACHER)
    students = [
        add_user(f"retry-{index}@example.com", UserRole.STUDENT, 2000 + index)
        for index in range(1, 3)
    ]
    reception, entries = add_active_session(teacher, students)
    published: list[dict[str, str]] = []
    monkeypatch.setattr(
        "backend.routes.queue.publish_session_event",
        lambda session_id, event_type: published.append(
            {"event_id": "retry-event", "type": event_type, "session_id": str(session_id)}
        ),
    )

    response = client.post(
        f"/sessions/{reception.id}/queue/{entries[0].id}/skip",
        headers=authorization(teacher),
    )
    assert response.status_code == 200

    failing = FakeTransport(failures=1)
    with SessionLocal() as db:
        process_queue_event(db, published[0], failing)
        failed = db.scalar(
            select(NotificationLog).where(
                NotificationLog.type == NotificationType.HARD_CALL
            )
        )
        assert failed.status == NotificationStatus.FAILED
        assert failed.attempts == 1
        assert db.get(QueueEntry, entries[0].id).status == QueueEntryStatus.SKIPPED

    recovered = FakeTransport()
    with SessionLocal() as db:
        assert retry_failed_notifications(db, recovered) == 1
        saved = db.scalar(select(NotificationLog))
        assert saved.status == NotificationStatus.SENT
        assert saved.attempts == 2
    assert len(recovered.sent) == 1
