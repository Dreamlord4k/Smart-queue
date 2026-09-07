from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

import backend.routes.sessions as session_routes
from backend.auth.dependencies import SessionLocal
from backend.auth.security import create_access_token
from backend.models.group import Group
from backend.models.session import Session
from backend.models.user import User, UserRole


def add_user(
    *,
    email: str,
    full_name: str,
    role: UserRole,
    group_id: UUID | None = None,
) -> User:
    with SessionLocal() as db:
        user = User(
            email=email,
            full_name=full_name,
            password_hash="not-used-in-freeze-tests",
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


def create_session(client: TestClient, teacher: User, **overrides) -> dict:
    response = client.post(
        "/sessions",
        headers=authorization(teacher),
        json=session_payload(**overrides),
    )
    assert response.status_code == 201
    return response.json()


def read_frozen(session_id: str | UUID) -> bool | None:
    with SessionLocal() as db:
        session_uuid = UUID(session_id) if isinstance(session_id, str) else session_id
        reception = db.scalar(select(Session).where(Session.id == session_uuid))
        return reception.frozen if reception else None


def test_owner_freezes_own_session(client: TestClient) -> None:
    teacher = add_user(
        email="owner@example.com", full_name="Владелец", role=UserRole.TEACHER
    )
    created = create_session(client, teacher)

    assert created["frozen"] is False

    response = client.post(
        f"/sessions/{created['id']}/freeze", headers=authorization(teacher)
    )

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["frozen"] is True


def test_student_and_other_teacher_are_forbidden(client: TestClient) -> None:
    owner = add_user(
        email="owner@example.com", full_name="Владелец", role=UserRole.TEACHER
    )
    other_teacher = add_user(
        email="other@example.com", full_name="Чужой", role=UserRole.TEACHER
    )
    group = add_group()
    student = add_user(
        email="student@example.com",
        full_name="Студент",
        role=UserRole.STUDENT,
        group_id=group.id,
    )
    created = create_session(client, owner)

    student_response = client.post(
        f"/sessions/{created['id']}/freeze", headers=authorization(student)
    )
    assert student_response.status_code == 403

    other_response = client.post(
        f"/sessions/{created['id']}/freeze", headers=authorization(other_teacher)
    )
    assert other_response.status_code == 403

    assert read_frozen(created["id"]) is False


def test_repeat_freeze_is_idempotent(client: TestClient) -> None:
    teacher = add_user(
        email="owner@example.com", full_name="Владелец", role=UserRole.TEACHER
    )
    created = create_session(client, teacher)

    first = client.post(
        f"/sessions/{created['id']}/freeze", headers=authorization(teacher)
    )
    second = client.post(
        f"/sessions/{created['id']}/freeze", headers=authorization(teacher)
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["frozen"] is True
    assert second.json()["frozen"] is True
    assert read_frozen(created["id"]) is True


def test_response_matches_stored_state(client: TestClient) -> None:
    teacher = add_user(
        email="owner@example.com", full_name="Владелец", role=UserRole.TEACHER
    )
    created = create_session(client, teacher)

    response = client.post(
        f"/sessions/{created['id']}/freeze", headers=authorization(teacher)
    )

    assert response.status_code == 200
    assert response.json()["frozen"] is True
    assert read_frozen(created["id"]) == response.json()["frozen"]


def test_freeze_unknown_session_returns_404(client: TestClient) -> None:
    teacher = add_user(
        email="owner@example.com", full_name="Владелец", role=UserRole.TEACHER
    )

    response = client.post(
        f"/sessions/{uuid4()}/freeze", headers=authorization(teacher)
    )

    assert response.status_code == 404


def test_owner_unfreezes_idempotently_and_publishes_once(
    client: TestClient, monkeypatch
) -> None:
    teacher = add_user(
        email="owner@example.com", full_name="Владелец", role=UserRole.TEACHER
    )
    created = create_session(client, teacher)
    assert client.post(
        f"/sessions/{created['id']}/freeze", headers=authorization(teacher)
    ).status_code == 200
    published: list[tuple[object, str]] = []
    monkeypatch.setattr(
        session_routes,
        "publish_session_event",
        lambda session_id, event: published.append((session_id, event)),
    )

    first = client.post(
        f"/sessions/{created['id']}/unfreeze", headers=authorization(teacher)
    )
    second = client.post(
        f"/sessions/{created['id']}/unfreeze", headers=authorization(teacher)
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["frozen"] is second.json()["frozen"] is False
    assert read_frozen(UUID(created["id"])) is False
    assert published == [(UUID(created["id"]), "session.unfrozen")]


def test_other_teacher_cannot_unfreeze(client: TestClient) -> None:
    owner = add_user(
        email="owner@example.com", full_name="Владелец", role=UserRole.TEACHER
    )
    other = add_user(
        email="other@example.com", full_name="Чужой", role=UserRole.TEACHER
    )
    created = create_session(client, owner)
    assert client.post(
        f"/sessions/{created['id']}/freeze", headers=authorization(owner)
    ).status_code == 200

    response = client.post(
        f"/sessions/{created['id']}/unfreeze", headers=authorization(other)
    )

    assert response.status_code == 403
    assert read_frozen(UUID(created["id"])) is True


def test_reorder_is_available_again_after_unfreeze(client: TestClient) -> None:
    owner = add_user(
        email="owner@example.com", full_name="Владелец", role=UserRole.TEACHER
    )
    first = add_user(
        email="first@example.com", full_name="Первый", role=UserRole.STUDENT
    )
    second = add_user(
        email="second@example.com", full_name="Второй", role=UserRole.STUDENT
    )
    created = create_session(
        client,
        owner,
        student_ids=[str(first.id), str(second.id)],
    )
    freeze_url = f"/sessions/{created['id']}/freeze"
    unfreeze_url = f"/sessions/{created['id']}/unfreeze"
    assert client.post(freeze_url, headers=authorization(owner)).status_code == 200
    assert client.post(unfreeze_url, headers=authorization(owner)).status_code == 200
    own_entry = next(
        entry for entry in created["queue"] if entry["student_id"] == str(first.id)
    )
    target_entry = next(
        entry for entry in created["queue"] if entry["student_id"] == str(second.id)
    )
    placement = "after" if own_entry["position"] < target_entry["position"] else "before"

    response = client.patch(
        f"/sessions/{created['id']}/queue/reorder",
        headers=authorization(first),
        json={
            "entry_id": own_entry["id"],
            "target_entry_id": target_entry["id"],
            "placement": placement,
        },
    )

    assert response.status_code == 200
    assert response.json()["new_position"] != own_entry["position"]
