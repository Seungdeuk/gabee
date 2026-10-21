from fastapi import FastAPI

from .config import settings
from .health.router import router as health_router

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.include_router(health_router)
