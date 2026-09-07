from __future__ import annotations

from datetime import date, time

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.auth.dependencies import SessionLocal
from backend.auth.security import create_access_token
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
            password_hash="not-used-in-queue-tests",
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
    course_name: str = "Алгоритмы",
    start_time: time = time(10, 0),
) -> tuple[Session, list[QueueEntry]]:
    with SessionLocal() as db:
        reception = Session(
            teacher_id=teacher.id,
            course_name=course_name,
            room="Р-123",
            date=date(2026, 9, 8),
            start_time=start_time,
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


def test_absence_keeps_row_normalizes_positions_and_recalculates_eta(
    client: TestClient,
) -> None:
    teacher = add_user("teacher@example.com", "Преподаватель", UserRole.TEACHER)
    first = add_user("first@example.com", "Первый", UserRole.STUDENT)
    leaving = add_user("leaving@example.com", "Второй", UserRole.STUDENT)
    third = add_user("third@example.com", "Третий", UserRole.STUDENT)
    _, entries = add_session(teacher, [first, leaving, third])

    response = client.post(
        f"/students/me/queues/{entries[1].id}/absence",
        headers=authorization(leaving),
        json={"absence_reason": "  Совпадает с экзаменом  "},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "absent"
    assert body["absence_reason"] == "Совпадает с экзаменом"
    assert [item["position"] for item in body["active_queue"]] == [1, 2]
    assert body["active_queue"][1]["student_id"] == str(third.id)
    assert body["active_queue"][1]["eta_start"] == "2026-09-08T10:15:00+05:00"

    with SessionLocal() as db:
        saved = db.get(QueueEntry, entries[1].id)
        assert saved is not None
        assert saved.status == QueueEntryStatus.ABSENT
        assert saved.absence_reason == "Совпадает с экзаменом"
        active = list(
            db.scalars(
                select(QueueEntry)
                .where(
                    QueueEntry.session_id == entries[1].session_id,
                    QueueEntry.status == QueueEntryStatus.WAITING,
                )
                .order_by(QueueEntry.position)
            ).all()
        )
        assert [entry.position for entry in active] == [1, 2]


def test_absence_can_only_change_own_entry(client: TestClient) -> None:
    teacher = add_user("teacher@example.com", "Преподаватель", UserRole.TEACHER)
    owner = add_user("owner@example.com", "Владелец", UserRole.STUDENT)
    stranger = add_user("stranger@example.com", "Другой", UserRole.STUDENT)
    _, entries = add_session(teacher, [owner])

    response = client.post(
        f"/students/me/queues/{entries[0].id}/absence",
        headers=authorization(stranger),
        json={},
    )

    assert response.status_code == 403
    with SessionLocal() as db:
        assert db.get(QueueEntry, entries[0].id).status == QueueEntryStatus.WAITING


def test_absence_reason_is_private_to_session_teacher(client: TestClient) -> None:
    teacher = add_user("teacher@example.com", "Преподаватель", UserRole.TEACHER)
    other_teacher = add_user("other@example.com", "Другой преподаватель", UserRole.TEACHER)
    student = add_user("student@example.com", "Студент", UserRole.STUDENT)
    reception, entries = add_session(teacher, [student])
    client.post(
        f"/students/me/queues/{entries[0].id}/absence",
        headers=authorization(student),
        json={"absence_reason": "Личная причина"},
    )

    teacher_response = client.get(
        f"/sessions/{reception.id}/queue", headers=authorization(teacher)
    )
    student_response = client.get(
        f"/sessions/{reception.id}/queue", headers=authorization(student)
    )
    other_response = client.get(
        f"/sessions/{reception.id}/queue", headers=authorization(other_teacher)
    )

    assert teacher_response.status_code == 200
    assert teacher_response.json()["entries"][0]["absence_reason"] == "Личная причина"
    assert student_response.status_code == 200
    assert student_response.json()["entries"][0]["absence_reason"] is None
    assert other_response.status_code == 403


def test_absence_does_not_change_another_session(client: TestClient) -> None:
    teacher = add_user("teacher@example.com", "Преподаватель", UserRole.TEACHER)
    student = add_user("student@example.com", "Студент", UserRole.STUDENT)
    _, first_entries = add_session(teacher, [student], course_name="Алгоритмы")
    _, second_entries = add_session(
        teacher, [student], course_name="Базы данных", start_time=time(10, 20)
    )

    response = client.post(
        f"/students/me/queues/{first_entries[0].id}/absence",
        headers=authorization(student),
        json={},
    )

    assert response.status_code == 200
    with SessionLocal() as db:
        assert db.get(QueueEntry, first_entries[0].id).status == QueueEntryStatus.ABSENT
        assert db.get(QueueEntry, second_entries[0].id).status == QueueEntryStatus.WAITING

    cards = client.get("/students/me/queues", headers=authorization(student))
    assert cards.status_code == 200
    assert [(card["course_name"], card["status"]) for card in cards.json()] == [
        ("Алгоритмы", "absent"),
        ("Базы данных", "waiting"),
    ]
    assert cards.json()[0]["position"] is None
    assert cards.json()[0]["eta_start"] is None
    assert cards.json()[1]["position"] == 1
