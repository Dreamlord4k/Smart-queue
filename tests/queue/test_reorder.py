from __future__ import annotations

from datetime import date, time

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.auth.dependencies import SessionLocal
from backend.auth.security import create_access_token
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.queue_move_log import QueueMoveLog
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


def add_session(
    teacher: User,
    students: list[User],
    *,
    frozen: bool = False,
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


def reorder(
    client: TestClient,
    reception: Session,
    entry: QueueEntry,
    student: User,
    *,
    target: QueueEntry | None,
    placement: str = "before",
):
    return client.patch(
        f"/sessions/{reception.id}/queue/reorder",
        headers=authorization(student),
        json={
            "entry_id": str(entry.id),
            "target_entry_id": str(target.id) if target else None,
            "placement": placement,
        },
    )


def test_student_cannot_reorder_another_students_entry(
    client: TestClient,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    owner = add_user("owner@example.com", UserRole.STUDENT)
    stranger = add_user("stranger@example.com", UserRole.STUDENT)
    reception, entries = add_session(teacher, [owner, stranger])

    response = reorder(
        client, reception, entries[0], stranger, target=entries[1], placement="after"
    )

    assert response.status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(QueueMoveLog)) is None


def test_reorder_rejects_locked_target_and_locked_destination(
    client: TestClient,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT)
        for index in range(1, 4)
    ]
    reception, entries = add_session(teacher, students)
    lock_response = client.patch(
        f"/sessions/{reception.id}/queue/{entries[1].id}/lock",
        headers=authorization(students[1]),
        json={"locked": True},
    )
    assert lock_response.status_code == 200

    locked_target = reorder(
        client, reception, entries[2], students[2], target=entries[1]
    )
    occupied_slot = reorder(
        client,
        reception,
        entries[2],
        students[2],
        target=entries[0],
        placement="after",
    )

    assert locked_target.status_code == 409
    assert occupied_slot.status_code == 409
    with SessionLocal() as db:
        saved = list(
            db.scalars(
                select(QueueEntry)
                .where(QueueEntry.session_id == reception.id)
                .order_by(QueueEntry.position)
            ).all()
        )
        assert [entry.id for entry in saved] == [entry.id for entry in entries]


def test_owner_must_unlock_before_reordering(client: TestClient) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT)
        for index in range(1, 4)
    ]
    reception, entries = add_session(teacher, students)
    lock_url = f"/sessions/{reception.id}/queue/{entries[0].id}/lock"

    assert client.patch(
        lock_url,
        headers=authorization(students[0]),
        json={"locked": True, "lock_reason": "Уже договорился"},
    ).status_code == 200
    assert reorder(
        client, reception, entries[0], students[0], target=entries[2], placement="after"
    ).status_code == 409
    assert client.patch(
        lock_url,
        headers=authorization(students[0]),
        json={"locked": False},
    ).status_code == 200

    response = reorder(
        client, reception, entries[0], students[0], target=entries[2], placement="after"
    )
    assert response.status_code == 200
    assert response.json()["new_position"] == 3


def test_frozen_session_rejects_reorder(client: TestClient) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT)
        for index in range(1, 3)
    ]
    reception, entries = add_session(teacher, students, frozen=True)

    response = reorder(
        client, reception, entries[0], students[0], target=entries[1], placement="after"
    )

    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(QueueMoveLog)) is None


def test_successful_reorder_normalizes_positions_and_writes_audit_log(
    client: TestClient,
) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    students = [
        add_user(f"student-{index}@example.com", UserRole.STUDENT)
        for index in range(1, 4)
    ]
    reception, entries = add_session(teacher, students)

    response = reorder(
        client, reception, entries[2], students[2], target=entries[0]
    )

    assert response.status_code == 200
    assert response.json()["old_position"] == 3
    assert response.json()["new_position"] == 1
    assert [item["position"] for item in response.json()["active_queue"]] == [1, 2, 3]
    with SessionLocal() as db:
        saved = list(
            db.scalars(
                select(QueueEntry)
                .where(QueueEntry.session_id == reception.id)
                .order_by(QueueEntry.position)
            ).all()
        )
        move_log = db.scalar(select(QueueMoveLog))
        assert [entry.id for entry in saved] == [
            entries[2].id,
            entries[0].id,
            entries[1].id,
        ]
        assert move_log is not None
        assert move_log.queue_entry_id == entries[2].id
        assert move_log.moved_by == students[2].id
        assert (move_log.old_position, move_log.new_position) == (3, 1)
        assert move_log.moved_at is not None


def test_lock_and_absence_reasons_remain_independent(client: TestClient) -> None:
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    student = add_user("student@example.com", UserRole.STUDENT)
    reception, entries = add_session(teacher, [student])

    lock_response = client.patch(
        f"/sessions/{reception.id}/queue/{entries[0].id}/lock",
        headers=authorization(student),
        json={"locked": True, "lock_reason": "  Удобно по расписанию  "},
    )
    absence_response = client.post(
        f"/students/me/queues/{entries[0].id}/absence",
        headers=authorization(student),
        json={"absence_reason": "  Другая встреча  "},
    )
    queue_response = client.get(
        f"/sessions/{reception.id}/queue", headers=authorization(teacher)
    )

    assert lock_response.status_code == 200
    assert lock_response.json()["lock_reason"] == "Удобно по расписанию"
    assert absence_response.status_code == 200
    assert queue_response.status_code == 200
    saved = queue_response.json()["entries"][0]
    assert saved["lock_reason"] == "Удобно по расписанию"
    assert saved["absence_reason"] == "Другая встреча"
