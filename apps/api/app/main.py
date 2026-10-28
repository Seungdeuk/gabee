from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.features.ai_assistant.router import router as ai_assistant_router
from app.features.billing.router import router as billing_router
from app.features.care.router import router as care_router
from app.features.family_chat.router import router as family_chat_router
from app.features.family_group.photo_limit import PhotoBodyLimitMiddleware
from app.features.family_group.router import router as family_group_router
from app.features.notifications.router import router as notifications_router
from app.features.schedule.router import router as schedule_router
from app.shared.config import settings
from app.shared.db import init_db
from app.shared.errors import register_error_handlers
from app.shared.high_risk_guard import GUARDED_FEATURES, high_risk_guard
from app.shared.privacy import ner as privacy_ner
from app.shared.route_switch import RouteSwitchMiddleware
from app.shared.schema_gate import health_router, schema_ready


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    privacy_ner.start_preload()  # NER 모델을 백그라운드로 미리 불러온다(off 면 아무 일도 안 함, 실패해도 기동은 계속)
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
app.add_middleware(
    RouteSwitchMiddleware
)  # DISABLED_AI_ROUTES 에 걸린 요청은 라우터 전에 503 (임시 방어)
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
    ("notifications", notifications_router),
):
    deps = [Depends(schema_ready(feature))]
    if feature in GUARDED_FEATURES:  # 고위험 입력(주민·카드·계좌·비밀번호) 사전 차단 (임시 방어)
        deps.append(Depends(high_risk_guard))
    app.include_router(router, dependencies=deps)
app.include_router(health_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
