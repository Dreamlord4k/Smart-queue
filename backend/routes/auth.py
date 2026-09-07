from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user, get_db
from backend.auth.schemas import (
    AccessTokenResponse,
    DemoLoginRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserResponse,
)
from backend.auth.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from backend.models.group import Group
from backend.models.user import User, UserRole
from backend.config import demo_mode_enabled
from backend.demo import (
    DEMO_STUDENT_EMAIL,
    DEMO_TEACHER_EMAIL,
    is_demo_user,
    reset_demo_ui,
)
from backend.realtime.events import publish_session_event


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    existing_user = db.scalar(select(User).where(User.email == str(payload.email)))
    if existing_user is not None:
        raise HTTPException(status_code=409, detail="Email уже зарегистрирован")

    if payload.role == UserRole.STUDENT and db.get(Group, payload.group_id) is None:
        raise HTTPException(status_code=422, detail="Указанная группа не найдена")

    user = User(
        email=str(payload.email),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        group_id=payload.group_id,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email уже зарегистрирован") from exc
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    user = db.scalar(select(User).where(User.email == str(payload.email)))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    return TokenPair(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user),
    )


@router.post("/demo-login", response_model=TokenPair)
def demo_login(payload: DemoLoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    if not demo_mode_enabled():
        raise HTTPException(status_code=404, detail="Демо-режим отключён")
    email = (
        DEMO_TEACHER_EMAIL
        if payload.role == UserRole.TEACHER
        else DEMO_STUDENT_EMAIL
    )
    user = db.scalar(select(User).where(User.email == email, User.role == payload.role))
    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Демо-данные не найдены — запустите scripts/seed_demo_ui.py",
        )
    return TokenPair(
        access_token=create_access_token(user, demo=True),
        refresh_token=create_refresh_token(user, demo=True),
    )


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> AccessTokenResponse:
    try:
        token_payload = decode_token(payload.refresh_token, expected_type="refresh")
        user = db.get(User, UUID(token_payload["sub"]))
        token_role = UserRole(token_payload["role"])
    except (TokenError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=401, detail="Недействительный refresh-токен") from exc

    if user is None or user.role != token_role:
        raise HTTPException(status_code=401, detail="Недействительный refresh-токен")
    return AccessTokenResponse(
        access_token=create_access_token(user, demo=token_payload.get("demo") is True)
    )


@router.post("/demo-reset")
def demo_reset(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    if not demo_mode_enabled() or not is_demo_user(current_user):
        raise HTTPException(status_code=403, detail="Сброс доступен только в демо-режиме")
    result = reset_demo_ui(db)
    publish_session_event(UUID(result["active_session_id"]), "demo.reset")
    publish_session_event(UUID(result["planned_session_id"]), "demo.reset")
    return result


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    if demo_mode_enabled() and is_demo_user(current_user):
        raise HTTPException(status_code=403, detail="Демо-профиль нельзя удалить")
    db.delete(current_user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
