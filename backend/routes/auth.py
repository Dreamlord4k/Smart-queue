from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth.dependencies import get_current_user, get_db
from backend.auth.schemas import (
    AccessTokenResponse,
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
    return AccessTokenResponse(access_token=create_access_token(user))


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    db.delete(current_user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
