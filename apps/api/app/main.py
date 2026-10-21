from fastapi import FastAPI

from .shared.config import settings

app = FastAPI(title=settings.app_name, debug=settings.debug)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
