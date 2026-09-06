from fastapi import FastAPI

from routes.auth import router as auth_router


app = FastAPI(title="Smart Queue API")
app.include_router(auth_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
