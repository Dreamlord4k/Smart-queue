from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.auth.dependencies import SessionLocal
from backend.auth.security import create_access_token
from backend.main import app
from backend.models.telegram_link_code import TelegramLinkCode
from backend.models.user import User, UserRole
from backend.notifications.transport import NotificationTransport
from backend.routes.telegram import get_telegram_transport


class FakeTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def send(self, telegram_id: int, message: str) -> None:
        self.sent.append((telegram_id, message))


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


def authorization(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def telegram_update(code: str, telegram_id: int = 123456) -> dict[str, object]:
    return {
        "update_id": 1,
        "message": {
            "text": f"/start {code}",
            "from": {"id": telegram_id},
            "chat": {"id": telegram_id},
        },
    }


def test_link_code_requires_account_and_is_one_time(client: TestClient) -> None:
    student = add_user("student@example.com", UserRole.STUDENT)
    teacher = add_user("teacher@example.com", UserRole.TEACHER)
    fake = FakeTransport()
    app.dependency_overrides[get_telegram_transport] = lambda: fake
    try:
        assert client.post("/telegram/link/init").status_code == 401
        assert (
            client.post("/telegram/link/init", headers=authorization(teacher)).status_code
            == 403
        )

        issued = client.post(
            "/telegram/link/init", headers=authorization(student)
        )
        assert issued.status_code == 200
        assert issued.json()["linked"] is False
        code = issued.json()["code"]

        linked = client.post("/telegram/webhook", json=telegram_update(code))
        replayed = client.post("/telegram/webhook", json=telegram_update(code))

        assert linked.status_code == 200
        assert replayed.status_code == 200
        assert "access_token" not in linked.text
        assert "refresh_token" not in linked.text
        with SessionLocal() as db:
            saved_user = db.get(User, student.id)
            saved_code = db.query(TelegramLinkCode).filter_by(code=code).one()
            assert saved_user.telegram_id == 123456
            assert saved_code.used_at is not None
        assert "успешно привязан" in fake.sent[0][1]
        assert "уже использован" in fake.sent[1][1]
    finally:
        app.dependency_overrides.pop(get_telegram_transport, None)


def test_expired_code_does_not_link_account(client: TestClient) -> None:
    student = add_user("expired@example.com", UserRole.STUDENT)
    with SessionLocal() as db:
        db.add(
            TelegramLinkCode(
                user_id=student.id,
                code="expired-code",
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            )
        )
        db.commit()

    fake: NotificationTransport = FakeTransport()
    app.dependency_overrides[get_telegram_transport] = lambda: fake
    try:
        response = client.post(
            "/telegram/webhook", json=telegram_update("expired-code", 999)
        )
        assert response.status_code == 200
        with SessionLocal() as db:
            assert db.get(User, student.id).telegram_id is None
            code = db.query(TelegramLinkCode).filter_by(code="expired-code").one()
            assert code.used_at is None
    finally:
        app.dependency_overrides.pop(get_telegram_transport, None)
