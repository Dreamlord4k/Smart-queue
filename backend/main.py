import os

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.auth.dependencies import engine
from backend.config import REDIS_URL, demo_mode_enabled
from backend.routes.auth import router as auth_router
from backend.routes.groups import router as groups_router
from backend.routes.queue import router as queue_router
from backend.routes.sessions import router as sessions_router
from backend.routes.telegram import router as telegram_router
from backend.routes.ws import router as ws_router


def _cors_origins() -> list[str]:
    raw_origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173")
    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    return origins or ["http://localhost:5173"]


app = FastAPI(title="Smart Queue API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(groups_router)
app.include_router(queue_router)
app.include_router(sessions_router)
app.include_router(telegram_router)
app.include_router(ws_router)


def _postgres_ready() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


def _redis_ready() -> bool:
    client = Redis.from_url(REDIS_URL)
    try:
        return bool(client.ping())
    except RedisError:
        return False
    finally:
        client.close()


@app.get("/health")
def health(response: Response) -> dict[str, object]:
    checks = {"postgres": _postgres_ready(), "redis": _redis_ready()}
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if ready else "unavailable",
        "checks": checks,
        "demo_mode": demo_mode_enabled(),
    }
