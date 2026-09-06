from dataclasses import dataclass
import os


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


@dataclass(frozen=True)
class AuthSettings:
    db_url: str
    jwt_secret: str
    access_ttl_minutes: int
    refresh_ttl_days: int
    jwt_algorithm: str = "HS256"


settings = AuthSettings(
    db_url=_required("DB_URL"),
    jwt_secret=_required("JWT_SECRET"),
    access_ttl_minutes=int(os.environ.get("JWT_ACCESS_TTL_MINUTES", "15")),
    refresh_ttl_days=int(os.environ.get("JWT_REFRESH_TTL_DAYS", "30")),
)
