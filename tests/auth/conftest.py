from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from auth.dependencies import SessionLocal
from main import app
from models.group import Group
from models.user import User


@pytest.fixture(autouse=True)
def clean_database() -> Generator[None, None, None]:
    with SessionLocal() as db:
        db.execute(delete(User))
        db.execute(delete(Group))
        db.commit()

    yield

    with SessionLocal() as db:
        db.execute(delete(User))
        db.execute(delete(Group))
        db.commit()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def group_id() -> str:
    with SessionLocal() as db:
        group = Group(name="ИРИТ-РТФ-301")
        db.add(group)
        db.commit()
        db.refresh(group)
        return str(group.id)
