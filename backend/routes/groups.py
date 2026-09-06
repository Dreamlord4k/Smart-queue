from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from backend.auth.dependencies import get_db
from backend.auth.security import TokenError, decode_token
from backend.models.group import Group
from backend.models.user import User, UserRole


router = APIRouter(tags=["groups"])
optional_bearer = HTTPBearer(auto_error=False)


class GroupStudentResponse(BaseModel):
    id: UUID
    full_name: str
    email: str


class GroupResponse(BaseModel):
    id: UUID
    name: str
    students: list[GroupStudentResponse] | None = None


def _require_teacher(
    credentials: HTTPAuthorizationCredentials | None,
    db: DatabaseSession,
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise credentials_error
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
        user = db.get(User, UUID(payload["sub"]))
        token_role = UserRole(payload["role"])
    except (TokenError, ValueError, KeyError) as exc:
        raise credentials_error from exc
    if user is None or user.role != token_role:
        raise credentials_error
    if user.role != UserRole.TEACHER:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return user


@router.get(
    "/groups",
    response_model=list[GroupResponse],
    response_model_exclude_none=True,
)
def list_groups(
    include_students: bool = False,
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    db: DatabaseSession = Depends(get_db),
) -> list[GroupResponse]:
    groups = list(db.scalars(select(Group).order_by(Group.name, Group.id)).all())
    if not include_students:
        return [GroupResponse(id=group.id, name=group.name) for group in groups]

    _require_teacher(credentials, db)
    students = list(
        db.scalars(
            select(User)
            .where(User.role == UserRole.STUDENT, User.group_id.is_not(None))
            .order_by(User.full_name, User.id)
        ).all()
    )
    students_by_group: dict[UUID, list[GroupStudentResponse]] = {
        group.id: [] for group in groups
    }
    for student in students:
        if student.group_id in students_by_group:
            students_by_group[student.group_id].append(
                GroupStudentResponse(
                    id=student.id,
                    full_name=student.full_name,
                    email=student.email,
                )
            )
    return [
        GroupResponse(
            id=group.id,
            name=group.name,
            students=students_by_group[group.id],
        )
        for group in groups
    ]
