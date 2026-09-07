from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.auth.dependencies import SessionLocal
from backend.models.group import Group
from backend.models.notification_log import NotificationLog, NotificationType
from backend.models.queue_entry import QueueEntry, QueueEntryStatus
from backend.models.session import Session, SessionStatus
from backend.models.user import User
from scripts.generate_demo_data import DemoApi, generate_demo_data
from scripts.run_demo_scenario import run_demo_scenario


class MemoryEvents:
    def __init__(self, published: list[dict[str, Any]]) -> None:
        self.published = published

    def next_event(
        self, session_id: str, expected_type: str, timeout: float = 3
    ) -> dict[str, Any]:
        for index, event in enumerate(self.published):
            if (
                event["session_id"] == session_id
                and event["type"] == expected_type
            ):
                return self.published.pop(index)
        raise AssertionError(f"Нет события {expected_type} для {session_id}")

    def close(self) -> None:
        return None


def test_repeatable_full_demo_uses_api_and_fake_telegram(
    client: TestClient, monkeypatch, tmp_path
) -> None:
    api = DemoApi("", client=client)
    state_path = tmp_path / "state.json"
    generation_args = {
        "db_url": SessionLocal.kw["bind"].url.render_as_string(
            hide_password=False
        ),
        "run_id": "pytest",
        "session_date": date(2026, 9, 8),
        "state_path": str(state_path),
    }

    first = generate_demo_data(api, **generation_args)
    second = generate_demo_data(api, **generation_args)

    assert first["run_id"] == second["run_id"] == "pytest"
    assert [group["id"] for group in first["groups"]] == [
        group["id"] for group in second["groups"]
    ]
    assert len(second["students"]) == 10
    assert {session["capacity"] for session in second["sessions"]} == {1, 2}
    assert all(len(session["queue"]) == 10 for session in second["sessions"])
    common_id = second["common_student_id"]
    assert all(
        common_id in {entry["student_id"] for entry in session["queue"]}
        for session in second["sessions"]
    )
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Group)) == 2
        assert db.scalar(select(func.count()).select_from(User)) == 11
        assert db.scalar(select(func.count()).select_from(Session)) == 2
        assert db.scalar(select(func.count()).select_from(QueueEntry)) == 20

    published: list[dict[str, Any]] = []

    def capture(session_id, event_type):
        event = {
            "event_id": str(uuid4()),
            "type": event_type,
            "session_id": str(session_id),
        }
        published.append(event)
        return event

    monkeypatch.setattr("backend.routes.queue.publish_session_event", capture)
    monkeypatch.setattr("backend.routes.sessions.publish_session_event", capture)
    summary = run_demo_scenario(
        api,
        second,
        MemoryEvents(published),
        delay_scale=0,
        sleep=lambda _: None,
        output=lambda _: None,
    )

    assert {item["capacity"] for item in summary["sessions"]} == {1, 2}
    assert all(item["ema_estimate"] is not None for item in summary["sessions"])
    assert all(item["eta_entries"] > 0 for item in summary["sessions"])
    assert summary["notification_types"] == ["buffer", "hard_call", "soft"]
    assert {event["type"] for event in summary["events"]} >= {
        "queue.absent",
        "queue.reordered",
        "queue.locked",
        "session.frozen",
        "session.updated",
        "queue.done",
        "queue.skipped",
    }
    with SessionLocal() as db:
        sessions = list(db.scalars(select(Session)).all())
        assert all(reception.status == SessionStatus.CLOSED for reception in sessions)
        absent_entries = list(
            db.scalars(
                select(QueueEntry).where(
                    QueueEntry.student_id == second["students"][-1]["id"]
                )
            ).all()
        )
        assert {entry.status for entry in absent_entries} >= {
            QueueEntryStatus.ABSENT,
            QueueEntryStatus.WAITING,
        }
        assert {
            notification.type
            for notification in db.scalars(select(NotificationLog)).all()
        } == {
            NotificationType.SOFT,
            NotificationType.BUFFER,
            NotificationType.HARD_CALL,
        }
