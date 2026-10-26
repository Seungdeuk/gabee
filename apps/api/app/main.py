from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.features.ai_assistant.router import router as ai_assistant_router
from app.features.billing.router import router as billing_router
from app.features.care.router import router as care_router
from app.features.family_chat.router import router as family_chat_router
from app.features.family_group.photo_limit import PhotoBodyLimitMiddleware
from app.features.family_group.router import router as family_group_router
from app.features.schedule.router import router as schedule_router
from app.shared.config import settings
from app.shared.db import init_db
from app.shared.errors import register_error_handlers
from app.shared.schema_gate import health_router, schema_ready


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

app.add_middleware(
    PhotoBodyLimitMiddleware
)  # 사진 업로드 경로만: multipart 파싱 전에 본문 크기로 거절
app.add_middleware(
    PhotoBodyLimitMiddleware,
    max_bytes=8 * 1024 * 1024 + 100 * 1024,
    path_suffix="/family-chat/photos",
    message="사진은 8MB 이하만 보낼 수 있어요",
)  # 채팅 사진(8MB + multipart 여유)
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
register_error_handlers(app)

# 기능별 스키마 의존성: 그 기능에 필요한 DB 스키마가 아직 준비되지 않았으면(자동 배포 중 등) 해당 기능만 503
for feature, router in (
    ("family_group", family_group_router),
    ("family_chat", family_chat_router),
    ("schedule", schedule_router),
    ("billing", billing_router),
    ("care", care_router),
    ("ai_assistant", ai_assistant_router),
):
    app.include_router(router, dependencies=[Depends(schema_ready(feature))])
app.include_router(health_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
