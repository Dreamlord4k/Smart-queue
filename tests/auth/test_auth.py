from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select

from auth.dependencies import SessionLocal, require_role
from auth.security import decode_token
from main import app
from models.user import User, UserRole


@app.get("/test/teacher-only")
def teacher_only(_: User = Depends(require_role(UserRole.TEACHER))) -> dict[str, bool]:
    return {"allowed": True}


def register_student(client: TestClient, group_id: str, email: str = "student@example.com"):
    return client.post(
        "/auth/register",
        json={
            "email": email,
            "full_name": "Иван Петров",
            "password": "correct horse battery staple",
            "role": "student",
            "group_id": group_id,
        },
    )


def login(client: TestClient, email: str, password: str = "correct horse battery staple"):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_login_returns_access_and_refresh_tokens(
    client: TestClient, group_id: str
) -> None:
    assert register_student(client, group_id).status_code == 201

    response = login(client, "STUDENT@example.com")

    assert response.status_code == 200
    tokens = response.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert decode_token(tokens["access_token"], "access")["role"] == "student"
    assert decode_token(tokens["refresh_token"], "refresh")["role"] == "student"

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "student@example.com"))
        assert user is not None
        assert user.password_hash != "correct horse battery staple"


def test_refresh_returns_new_access_without_password(
    client: TestClient, group_id: str
) -> None:
    assert register_student(client, group_id).status_code == 201
    tokens = login(client, "student@example.com").json()

    response = client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert response.status_code == 200
    refreshed = response.json()
    assert refreshed["access_token"] != tokens["access_token"]
    assert decode_token(refreshed["access_token"], "access")["role"] == "student"


def test_student_cannot_access_teacher_only_endpoint(
    client: TestClient, group_id: str
) -> None:
    assert register_student(client, group_id).status_code == 201
    student_token = login(client, "student@example.com").json()["access_token"]

    forbidden = client.get(
        "/test/teacher-only", headers={"Authorization": f"Bearer {student_token}"}
    )

    assert forbidden.status_code == 403

    assert client.post(
        "/auth/register",
        json={
            "email": "teacher@example.com",
            "full_name": "Иван Петров",
            "password": "another correct password",
            "role": "teacher",
        },
    ).status_code == 201
    teacher_token = login(
        client, "teacher@example.com", "another correct password"
    ).json()["access_token"]
    allowed = client.get(
        "/test/teacher-only", headers={"Authorization": f"Bearer {teacher_token}"}
    )
    assert allowed.status_code == 200


def test_email_is_unique_but_names_may_repeat(
    client: TestClient, group_id: str
) -> None:
    assert register_student(client, group_id, "first@example.com").status_code == 201
    assert register_student(client, group_id, "second@example.com").status_code == 201
    assert register_student(client, group_id, "FIRST@example.com").status_code == 409


def test_delete_me_removes_account_and_invalidates_refresh(
    client: TestClient, group_id: str
) -> None:
    assert register_student(client, group_id).status_code == 201
    tokens = login(client, "student@example.com").json()

    response = client.delete(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert response.status_code == 204
    assert login(client, "student@example.com").status_code == 401
    assert client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    ).status_code == 401
