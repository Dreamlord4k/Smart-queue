from sqlalchemy import func, select

from backend.auth.dependencies import SessionLocal
from backend.auth.security import decode_token
from backend.demo import (
    DEMO_ACTIVE_SESSION_ID,
    DEMO_STUDENT_EMAIL,
    DEMO_TEACHER_EMAIL,
    reset_demo_ui,
)
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.session import Session, SessionStatus
from backend.models.user import User


def _demo_login(client, role: str):
    return client.post("/auth/demo-login", json={"role": role})


def test_demo_login_is_disabled_without_flag(client, monkeypatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)

    assert _demo_login(client, "teacher").status_code == 404
    assert client.get("/health").json()["demo_mode"] is False


def test_demo_login_requires_seed_and_marks_both_roles(client, monkeypatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")

    assert client.get("/health").json()["demo_mode"] is True

    missing = _demo_login(client, "teacher")
    assert missing.status_code == 404
    assert "seed_demo_ui.py" in missing.json()["detail"]

    with SessionLocal() as db:
        reset_demo_ui(db)

    teacher = _demo_login(client, "teacher")
    student = _demo_login(client, "student")

    assert teacher.status_code == student.status_code == 200
    assert decode_token(teacher.json()["access_token"], "access")["demo"] is True
    assert decode_token(student.json()["refresh_token"], "refresh")["demo"] is True

    refreshed = client.post(
        "/auth/refresh", json={"refresh_token": student.json()["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert decode_token(refreshed.json()["access_token"], "access")["demo"] is True


def test_demo_reset_is_idempotent_and_keeps_tokens_valid(client, monkeypatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    with SessionLocal() as db:
        first = reset_demo_ui(db)
        second = reset_demo_ui(db)

    assert first == second
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 9
        assert db.scalar(select(func.count()).select_from(Session)) == 2
        assert db.scalar(select(func.count()).select_from(QueueEntry)) == 16
        active = db.get(Session, DEMO_ACTIVE_SESSION_ID)
        assert active is not None
        assert active.status == SessionStatus.ACTIVE
        assert active.frozen is True
        assert db.scalar(
            select(func.count()).select_from(QueueEntry).where(
                QueueEntry.session_id == active.id,
                QueueEntry.status == QueueEntryStatus.CALLED,
            )
        ) == 2

    student_tokens = _demo_login(client, "student").json()
    with SessionLocal() as db:
        entry = db.scalar(
            select(QueueEntry).where(QueueEntry.session_id == DEMO_ACTIVE_SESSION_ID)
        )
        assert entry is not None
        entry.status = QueueEntryStatus.DONE
        db.commit()

    reset = client.post(
        "/auth/demo-reset",
        headers={"Authorization": f"Bearer {student_tokens['access_token']}"},
    )
    assert reset.status_code == 200
    assert reset.json()["active_session_id"] == str(DEMO_ACTIVE_SESSION_ID)
    assert client.get(
        "/students/me/queues",
        headers={"Authorization": f"Bearer {student_tokens['access_token']}"},
    ).status_code == 200


def test_demo_accounts_cannot_be_deleted(client, monkeypatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    with SessionLocal() as db:
        reset_demo_ui(db)
        assert db.scalar(select(User).where(User.email == DEMO_TEACHER_EMAIL))
        assert db.scalar(select(User).where(User.email == DEMO_STUDENT_EMAIL))

    token = _demo_login(client, "student").json()["access_token"]
    response = client.delete(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403
