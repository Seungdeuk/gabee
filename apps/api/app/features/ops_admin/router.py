"""운영 관리자 조회 API (/admin/ops/*). 읽기 전용이며 ops_admin 허용 목록에 있는 운영자만 쓸 수 있다."""

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.shared.auth import require_operator
from app.shared.db import get_db
from app.shared.errors import not_found

from . import (
    admin_facts,  # noqa: F401  관리자 챗봇 숫자 명단에 올린다
    alert_rules,  # noqa: F401  관리자 알림 규칙(서버 오류율)을 명단에 올린다
    infra_service,
    query_service,
)
from .schemas import (
    ApisOut,
    ErrorEventOut,
    ErrorKind,
    ErrorListOut,
    InfraOut,
    RangeKey,
    SummaryOut,
)

router = APIRouter(prefix="/admin/ops", tags=["ops-admin"])


@router.get("/summary", response_model=SummaryOut)
def get_summary(
    range: RangeKey = Query("24h"),
    _: object = Depends(require_operator("admin")),
    db: Session = Depends(get_db),
) -> SummaryOut:
    return query_service.summary(db, range)


@router.get("/apis", response_model=ApisOut)
def get_apis(
    range: RangeKey = Query("24h"),
    _: object = Depends(require_operator("admin")),
    db: Session = Depends(get_db),
) -> ApisOut:
    return query_service.apis(db, range)


@router.get("/infra", response_model=InfraOut)
def get_infra(_: object = Depends(require_operator("admin"))) -> InfraOut:
    return infra_service.get_infra()


@router.get("/errors", response_model=ErrorListOut)
def get_errors(
    range: RangeKey = Query("24h"),
    kind: ErrorKind | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    _: object = Depends(require_operator("admin")),
    db: Session = Depends(get_db),
) -> ErrorListOut:
    return query_service.errors(db, range, kind, limit)


@router.get("/errors/{event_id}", response_model=ErrorEventOut)
def get_error(
    event_id: str = Path(pattern="^[0-9a-f]{64}$"),
    _: object = Depends(require_operator("admin")),
    db: Session = Depends(get_db),
) -> ErrorEventOut:
    event = query_service.error_detail(db, event_id)
    if event is None:
        raise not_found("오류 기록")
    return event
