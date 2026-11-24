"""체류시간 기록. 로그인한 본인 것만 저장하고 가족이 없어도 된다 — docs/requirements/usage-time.md."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.auth import current_user
from app.shared.db import get_db

from . import service
from .schemas import UsageReportIn

router = APIRouter(prefix="/usage", tags=["usage"])


@router.post("/report", status_code=204)
def report_usage(
    body: UsageReportIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
    """앱이 백그라운드로 갈 때 보낸 사용 기록(그날 탭별 초, 실행 횟수)을 하루 합계에 더한다."""
    service.report(db, user, body)
