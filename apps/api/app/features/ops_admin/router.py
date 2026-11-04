"""운영 관리자 조회 API (/admin/ops/*). 읽기 전용이며 ops_admin 허용 목록에 있는 운영자만 쓸 수 있다."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.shared.auth import require_operator
from app.shared.db import get_db

from . import query_service
from .schemas import ApisOut, RangeKey, SummaryOut

router = APIRouter(prefix="/admin/ops", tags=["ops-admin"])


@router.get("/summary", response_model=SummaryOut)
def get_summary(
    range: RangeKey = Query("24h"),
    _: object = Depends(require_operator("ops_admin")),
    db: Session = Depends(get_db),
) -> SummaryOut:
    return query_service.summary(db, range)


@router.get("/apis", response_model=ApisOut)
def get_apis(
    range: RangeKey = Query("24h"),
    _: object = Depends(require_operator("ops_admin")),
    db: Session = Depends(get_db),
) -> ApisOut:
    return query_service.apis(db, range)
