from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.auth.dependencies import SessionLocal
from backend.main import app
from backend.models.group import Group
from backend.models.notification_log import NotificationLog
from backend.models.queue_entry import QueueEntry
from backend.models.queue_move_log import QueueMoveLog
from backend.models.service_stat import ServiceStat
from backend.models.session import Session
from backend.models.telegram_link_code import TelegramLinkCode
from backend.models.user import User


def _clean_database() -> None:
    with SessionLocal() as db:
        db.execute(delete(NotificationLog))
        db.execute(delete(TelegramLinkCode))
        db.execute(delete(QueueMoveLog))
        db.execute(delete(ServiceStat))
        db.execute(delete(QueueEntry))
        db.execute(delete(Session))
        db.execute(delete(User))
        db.execute(delete(Group))
        db.commit()


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    _clean_database()
    yield
    _clean_database()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
