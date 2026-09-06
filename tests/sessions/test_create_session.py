from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.auth.dependencies import SessionLocal
from backend.auth.security import create_access_token
from backend.models.group import Group
from backend.models.queue_entry import QueueEntry
from backend.models.session import Session, SessionStatus
from backend.models.user import User, UserRole
from backend.routes.sessions import CreateSessionRequest


def add_user(
    *,
    email: str,
    full_name: str,
    role: UserRole,
    group_id: UUID | None = None,
    user_id: UUID | None = None,
) -> User:
    with SessionLocal() as db:
        user = User(
            id=user_id,
            email=email,
            full_name=full_name,
            password_hash="not-used-in-session-tests",
            role=role,
            group_id=group_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def add_group(name: str = "ИРИТ-РТФ-301") -> Group:
    with SessionLocal() as db:
        group = Group(name=name)
        db.add(group)
        db.commit()
        db.refresh(group)
        db.expunge(group)
        return group


def authorization(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def session_payload(**overrides):
    payload = {
        "course_name": "Алгоритмы",
        "room": "Р-123",
        "date": "2026-09-08",
        "start_time": "10:00:00",
        "duration_default": 15,
        "capacity": 2,
        "group_ids": [],
        "student_ids": [],
    }
    payload.update(overrides)
    return payload


def test_creation_builds_unique_alphabetical_queue(client: TestClient) -> None:
    group = add_group()
    teacher = add_user(
        email="teacher@example.com", full_name="Преподаватель", role=UserRole.TEACHER
    )
    anna_second = add_user(
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        email="anna2@example.com",
        full_name="Анна Иванова",
        role=UserRole.STUDENT,
        group_id=group.id,
    )
    boris = add_user(
        email="boris@example.com",
        full_name="Борис Сидоров",
        role=UserRole.STUDENT,
        group_id=group.id,
    )
    anna_first = add_user(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        email="anna1@example.com",
        full_name="Анна Иванова",
        role=UserRole.STUDENT,
    )

    response = client.post(
        "/sessions",
        headers=authorization(teacher),
        json=session_payload(
            group_ids=[str(group.id)], student_ids=[str(anna_first.id)]
        ),
    )

    assert response.status_code == 201
    assert response.json()["frozen"] is False
    assert response.json()["status"] == "planned"
    assert [entry["student_id"] for entry in response.json()["queue"]] == [
        str(anna_first.id),
        str(anna_second.id),
        str(boris.id),
    ]
    assert [entry["position"] for entry in response.json()["queue"]] == [1, 2, 3]


def test_group_and_explicit_selection_do_not_duplicate_student(
    client: TestClient,
) -> None:
    group = add_group()
    teacher = add_user(
        email="teacher@example.com", full_name="Преподаватель", role=UserRole.TEACHER
    )
    student = add_user(
        email="student@example.com",
        full_name="Студент",
        role=UserRole.STUDENT,
        group_id=group.id,
    )

    response = client.post(
        "/sessions",
        headers=authorization(teacher),
        json=session_payload(
            group_ids=[str(group.id)], student_ids=[str(student.id), str(student.id)]
        ),
    )

    assert response.status_code == 201
    assert len(response.json()["queue"]) == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(QueueEntry)) == 1


def test_empty_queue_does_not_cancel_session(client: TestClient) -> None:
    teacher = add_user(
        email="teacher@example.com", full_name="Преподаватель", role=UserRole.TEACHER
    )

    response = client.post(
        "/sessions", headers=authorization(teacher), json=session_payload()
    )

    assert response.status_code == 201
    assert response.json()["queue"] == []
    with SessionLocal() as db:
        reception = db.scalar(select(Session))
        assert reception is not None
        assert reception.status == SessionStatus.PLANNED


def test_student_cannot_create_session(client: TestClient) -> None:
    group = add_group()
    student = add_user(
        email="student@example.com",
        full_name="Студент",
        role=UserRole.STUDENT,
        group_id=group.id,
    )

    response = client.post(
        "/sessions", headers=authorization(student), json=session_payload()
    )

    assert response.status_code == 403


def test_rsvp_fields_are_absent() -> None:
    assert all("rsvp" not in name.lower() for name in CreateSessionRequest.model_fields)
    assert all("rsvp" not in column.name.lower() for column in Session.__table__.columns)
    assert all("rsvp" not in column.name.lower() for column in QueueEntry.__table__.columns)
