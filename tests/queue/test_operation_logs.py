from __future__ import annotations

import json
import logging

import pytest
from datetime import date, time
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.auth.dependencies import SessionLocal
from backend.auth.security import create_access_token
from backend.logging_config import LOGGER_NAME
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.session import Session, SessionStatus
from backend.models.user import User, UserRole


def authorization(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def add_user(email: str, name: str, role: UserRole) -> User:
    with SessionLocal() as db:
        user = User(
            email=email,
            full_name=name,
            password_hash="not-used-in-log-tests",
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def add_session(
    teacher: User, students: list[User]
) -> tuple[Session, list[QueueEntry]]:
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


def log_fields(caplog: pytest.LogCaptureFixture, op: str) -> dict:
    records = [
        record
        for record in caplog.records
        if record.name == LOGGER_NAME
        and record.getMessage() == op
    ]
    assert records, f"нет info-записи операции {op}"
    return dict(records[-1].fields)


def test_freeze_logs_operation_and_keeps_result(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    teacher = add_user("teacher@example.com", "Преподаватель", UserRole.TEACHER)
    student = add_user("student@example.com", "Студент", UserRole.STUDENT)
    reception, _ = add_session(teacher, [student])

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        response = client.post(
            f"/sessions/{reception.id}/freeze", headers=authorization(teacher)
        )

    assert response.status_code == 200
    assert response.json()["frozen"] is True
    fields = log_fields(caplog, "session.frozen")
    assert fields["session_id"] == str(reception.id)
    assert fields["actor_id"] == str(teacher.id)
    assert fields["frozen_before"] is False
    assert fields["frozen_after"] is True
    assert "entry_id" not in fields


def test_absence_logs_operation_and_keeps_result(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    teacher = add_user("teacher@example.com", "Преподаватель", UserRole.TEACHER)
    first = add_user("first@example.com", "Первый", UserRole.STUDENT)
    leaving = add_user("leaving@example.com", "Второй", UserRole.STUDENT)
    reception, entries = add_session(teacher, [first, leaving])

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        response = client.post(
            f"/students/me/queues/{entries[1].id}/absence",
            headers=authorization(leaving),
            json={},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "absent"
    fields = log_fields(caplog, "queue.absent")
    assert fields["session_id"] == str(reception.id)
    assert fields["entry_id"] == str(entries[1].id)
    assert fields["actor_id"] == str(leaving.id)
    assert fields["position_before"] == 2
    assert fields["status_before"] == "waiting"


def test_reorder_logs_positions_and_keeps_result(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    teacher = add_user("teacher@example.com", "Преподаватель", UserRole.TEACHER)
    first = add_user("first@example.com", "Первый", UserRole.STUDENT)
    second = add_user("second@example.com", "Второй", UserRole.STUDENT)
    third = add_user("third@example.com", "Третий", UserRole.STUDENT)
    reception, entries = add_session(teacher, [first, second, third])

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        response = client.patch(
            f"/sessions/{reception.id}/queue/reorder",
            headers=authorization(third),
            json={
                "entry_id": str(entries[2].id),
                "target_entry_id": str(entries[0].id),
                "placement": "before",
            },
        )

    assert response.status_code == 200
    assert response.json()["old_position"] == 3
    assert response.json()["new_position"] == 1
    fields = log_fields(caplog, "queue.reordered")
    assert fields["position_before"] == 3
    assert fields["position_after"] == 1
    assert fields["actor_id"] == str(third.id)
    with SessionLocal() as db:
        positions = db.scalars(
            select(QueueEntry.position)
            .where(QueueEntry.session_id == reception.id)
            .order_by(QueueEntry.position)
        ).all()
        assert list(positions) == [1, 2, 3]


def test_log_lines_are_single_json_without_secrets(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    teacher = add_user("teacher@example.com", "Преподаватель", UserRole.TEACHER)
    student = add_user("student@example.com", "Студент", UserRole.STUDENT)
    reception, _ = add_session(teacher, [student])

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        assert (
            client.post(
                f"/sessions/{reception.id}/freeze", headers=authorization(teacher)
            ).status_code
            == 200
        )

    records = [
        record
        for record in caplog.records
        if record.name == LOGGER_NAME
    ]
    assert records
    for record in records:
        line = json.dumps(
            {"op": record.getMessage(), **dict(record.fields)},
            ensure_ascii=False,
        )
        assert "\n" not in line
        lowered = line.lower()
        assert "access_token" not in lowered
        assert "password" not in lowered
        assert "bearer" not in lowered
        assert isinstance(UUID(str(dict(record.fields).get("session_id"))), UUID)
