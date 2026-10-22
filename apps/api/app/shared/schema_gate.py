"""기능별 스키마 의존성(503)과 DB 상태 확인 API.

각 기능 router 는 main.py 에서 `Depends(schema_ready(<기능>))` 와 함께 등록된다. 그 기능(과 전제인 family_group)이
쓰는 테이블·컬럼이 실제 DB 에 준비돼 있을 때만 요청을 통과시키고, 아니면 503 을 돌려준다 —
준비된 기능은 영향받지 않으므로 DB 가 일시적으로 뒤처져도 서버 전체가 멈추지 않는다.
"""

from collections.abc import Callable

from fastapi import APIRouter

from .errors import ApiError
from .schema import monitor

RETRY_AFTER = {"Retry-After": "5"}

health_router = APIRouter(tags=["health"])


def schema_ready(feature: str) -> Callable[[], None]:
    def dependency() -> None:
        status = monitor.status()
        if status.feature_ready(feature):
            return
        if not status.db_connected:
            raise ApiError(
                503,
                "db_unavailable",
                "데이터베이스에 연결할 수 없어요. 잠시 후 다시 시도해 주세요",
                RETRY_AFTER,
            )
        raise ApiError(
            503,
            "schema_not_ready",
            "이 기능에 필요한 데이터베이스 준비가 아직 끝나지 않았어요(업데이트 중일 수 있어요). 잠시 후 다시 시도해 주세요",
            RETRY_AFTER,
        )

    return dependency


@health_router.get("/health/db")
def db_health() -> dict:
    """DB 연결·리비전·스키마 준비 상태. 최신 상태를 다시 점검한다(짧은 간격 제한 있음).
    비밀번호·접속 주소·테이블/컬럼 이름은 응답에 싣지 않는다."""
    return monitor.status(force=True).public()
