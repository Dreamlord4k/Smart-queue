from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.auth.dependencies import SessionLocal
from backend.main import app
from backend.models.group import Group
from backend.models.queue_entry import QueueEntry
from backend.models.service_stat import ServiceStat
from backend.models.session import Session
from backend.models.user import User


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    with SessionLocal() as db:
        db.execute(delete(ServiceStat))
        db.execute(delete(QueueEntry))
        db.execute(delete(Session))
        db.execute(delete(User))
        db.execute(delete(Group))
        db.commit()

    yield

    with SessionLocal() as db:
        db.execute(delete(ServiceStat))
        db.execute(delete(QueueEntry))
        db.execute(delete(Session))
        db.execute(delete(User))
        db.execute(delete(Group))
        db.commit()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
