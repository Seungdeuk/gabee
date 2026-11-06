from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.features.ai_assistant.router import router as ai_assistant_router
from app.features.billing.router import router as billing_router
from app.features.family_chat.router import router as family_chat_router
from app.features.family_group.photo_limit import PhotoBodyLimitMiddleware
from app.features.family_group.router import router as family_group_router
from app.features.notices.router import router as notices_router
from app.features.notifications.router import router as notifications_router
from app.features.ops_admin.error_service import observe as ops_error_observer
from app.features.ops_admin.middleware import RequestMetricsMiddleware
from app.features.ops_admin.router import router as ops_admin_router
from app.features.ops_admin.service import aggregator as ops_metrics
from app.features.schedule.router import router as schedule_router
from app.features.service_admin.router import router as admin_router
from app.features.support.router import router as support_router
from app.shared.config import settings
from app.shared.db import init_db
from app.shared.errors import register_error_handlers, set_error_observer
from app.shared.high_risk_guard import GUARDED_FEATURES, high_risk_guard
from app.shared.privacy import ner as privacy_ner
from app.shared.public_pages.router import router as public_pages_router
from app.shared.route_switch import RouteSwitchMiddleware
from app.shared.schema_gate import health_router, schema_ready


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    privacy_ner.start_preload()  # NER 모델을 백그라운드로 미리 불러온다(off 면 아무 일도 안 함, 실패해도 기동은 계속)
    yield
    ops_metrics.flush(
        final=True
    )  # 종료 전에 남은 요청 지표를 저장한다(꺼져 있으면 비어 있고, 실패해도 종료는 계속)


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
    PhotoBodyLimitMiddleware,
    max_bytes=20 * 1024 * 1024 + 100 * 1024,
    path_suffix="/family-chat/files",
    message="파일은 20MB 이하만 보낼 수 있어요",
    code="file_too_large",
)  # 채팅 문서 파일(20MB + multipart 여유)
app.add_middleware(
    RouteSwitchMiddleware
)  # DISABLED_AI_ROUTES 에 걸린 요청은 라우터 전에 503 (임시 방어)
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(
    RequestMetricsMiddleware
)  # 가장 바깥: OPS_METRICS_ENABLED 가 켜졌을 때만 X-Trace-Id 발급·요청 지표 집계(기본 꺼짐)
register_error_handlers(app)
set_error_observer(
    ops_error_observer
)  # 5xx·처리되지 않은 예외·401/403 을 운영 오류 이벤트로(OPS_ERRORS_ENABLED, 기본 꺼짐)

# 기능별 스키마 의존성: 그 기능에 필요한 DB 스키마가 아직 준비되지 않았으면(자동 배포 중 등) 해당 기능만 503
for feature, router in (
    ("family_group", family_group_router),
    ("family_chat", family_chat_router),
    ("schedule", schedule_router),
    ("billing", billing_router),
    ("ai_assistant", ai_assistant_router),
    ("notifications", notifications_router),
    ("support", support_router),
    ("notices", notices_router),
    ("ops_admin", ops_admin_router),
):
    deps = []
    deps.append(Depends(schema_ready(feature)))
    if feature in GUARDED_FEATURES:  # 고위험 입력(주민·카드·계좌·비밀번호) 사전 차단 (임시 방어)
        deps.append(Depends(high_risk_guard))
    app.include_router(router, dependencies=deps)
# 서비스 관리자 API 는 자기 모델이 없고 다른 기능의 표를 개수만 읽는다(권한은 require_operator("service_admin"))
app.include_router(admin_router, dependencies=[Depends(schema_ready("family_group"))])
# 서비스 관리자 화면(정적 파일). 데이터는 화면이 로그인한 뒤 /admin/service/* API 로 받는다
_ADMIN_STATIC = Path(__file__).parent / "features" / "service_admin" / "static"
app.mount(
    "/admin/service/ui", StaticFiles(directory=_ADMIN_STATIC, html=True), name="service_admin_ui"
)
app.include_router(health_router)
app.include_router(public_pages_router)  # 공개 안내 페이지(/, /privacy, /terms): 로그인·DB 없음


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
