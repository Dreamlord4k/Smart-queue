from collections.abc import Callable, Generator
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.auth.config import settings
from backend.auth.security import TokenError, decode_token
from backend.models.user import User, UserRole


engine = create_engine(settings.db_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token, expected_type="access")
        user_id = UUID(payload["sub"])
        token_role = UserRole(payload["role"])
    except (TokenError, ValueError, KeyError) as exc:
        raise credentials_error from exc

    user = db.get(User, user_id)
    if user is None or user.role != token_role:
        raise credentials_error
    return user


def require_role(role: UserRole) -> Callable[..., User]:
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав",
            )
        return current_user

    return dependency
