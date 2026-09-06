from __future__ import annotations

from fastapi.testclient import TestClient

from backend.auth.dependencies import SessionLocal
from backend.auth.security import create_access_token
from backend.models.group import Group
from backend.models.user import User, UserRole


def authorization(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def add_user(
    email: str,
    role: UserRole,
    *,
    full_name: str,
    group: Group | None = None,
) -> User:
    with SessionLocal() as db:
        user = User(
            email=email,
            full_name=full_name,
            password_hash="not-used-in-group-tests",
            role=role,
            group_id=group.id if group else None,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def add_group(name: str) -> Group:
    with SessionLocal() as db:
        group = Group(name=name)
        db.add(group)
        db.commit()
        db.refresh(group)
        db.expunge(group)
        return group


def test_public_groups_are_minimal(client: TestClient) -> None:
    second = add_group("ИРИТ-РТФ-302")
    first = add_group("ИРИТ-РТФ-301")
    add_user(
        "student@example.com",
        UserRole.STUDENT,
        full_name="Студент",
        group=first,
    )

    response = client.get("/groups")

    assert response.status_code == 200
    assert response.json() == [
        {"id": str(first.id), "name": first.name},
        {"id": str(second.id), "name": second.name},
    ]


def test_only_teacher_can_request_group_rosters(client: TestClient) -> None:
    group = add_group("ИРИТ-РТФ-301")
    teacher = add_user(
        "teacher@example.com", UserRole.TEACHER, full_name="Преподаватель"
    )
    student = add_user(
        "student@example.com",
        UserRole.STUDENT,
        full_name="Борис Сидоров",
        group=group,
    )
    anna = add_user(
        "anna@example.com",
        UserRole.STUDENT,
        full_name="Анна Иванова",
        group=group,
    )

    assert client.get("/groups?include_students=true").status_code == 401
    assert client.get(
        "/groups?include_students=true", headers=authorization(student)
    ).status_code == 403

    response = client.get(
        "/groups?include_students=true", headers=authorization(teacher)
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(group.id),
            "name": group.name,
            "students": [
                {
                    "id": str(anna.id),
                    "full_name": anna.full_name,
                    "email": anna.email,
                },
                {
                    "id": str(student.id),
                    "full_name": student.full_name,
                    "email": student.email,
                },
            ],
        }
    ]
