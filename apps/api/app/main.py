from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.features.ai_assistant.router import router as ai_assistant_router
from app.features.billing.router import router as billing_router
from app.features.care.router import router as care_router
from app.features.family_chat.router import router as family_chat_router
from app.features.family_group.router import router as family_group_router
from app.features.schedule.router import router as schedule_router
from app.shared.config import settings
from app.shared.db import init_db
from app.shared.errors import register_error_handlers


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
register_error_handlers(app)

for router in (
    family_group_router,
    family_chat_router,
    schedule_router,
    billing_router,
    care_router,
    ai_assistant_router,
):
    app.include_router(router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
