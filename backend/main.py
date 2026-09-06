from fastapi import FastAPI

from routes.auth import router as auth_router
from routes.sessions import router as sessions_router


app = FastAPI(title="Smart Queue API")
app.include_router(auth_router)
app.include_router(sessions_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
