from fastapi import FastAPI


app = FastAPI(title="Smart Queue API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
