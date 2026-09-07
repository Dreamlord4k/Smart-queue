import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
