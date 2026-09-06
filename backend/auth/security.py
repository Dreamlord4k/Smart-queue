from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
import jwt
from jwt import InvalidTokenError

from auth.config import settings
from models.user import User


_password_hasher = PasswordHasher()


class TokenError(ValueError):
    pass


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def _create_token(user: User, token_type: str, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user: User) -> str:
    return _create_token(
        user, "access", timedelta(minutes=settings.access_ttl_minutes)
    )


def create_refresh_token(user: User) -> str:
    return _create_token(user, "refresh", timedelta(days=settings.refresh_ttl_days))


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except InvalidTokenError as exc:
        raise TokenError("Недействительный токен") from exc

    if payload.get("type") != expected_type:
        raise TokenError("Неверный тип токена")
    if not payload.get("sub") or not payload.get("role"):
        raise TokenError("В токене отсутствуют обязательные поля")
    return payload
