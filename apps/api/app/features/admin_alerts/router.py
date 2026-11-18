"""관리자 알림 주소.

- 점검 주소 `POST /internal/alerts/run`: 외부 스케줄러가 5분마다 부른다. 사용자 인증이 아니라 비밀 토큰(`X-Alert-Token`)으로 막는다.
- 목록·확인 주소 `/admin/alerts`: 통합관리자(require_operator("admin"))만 쓴다.
"""

import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.shared.auth import require_operator
from app.shared.config import settings
from app.shared.db import get_db
from app.shared.errors import ApiError

from . import service
from .models import AdminAlertLog
from .schemas import AlertItemOut, AlertListOut, RunOut

admin_router = APIRouter(prefix="/admin/alerts", tags=["admin-alerts"])
internal_router = APIRouter(prefix="/internal/alerts", tags=["admin-alerts-internal"])


def _check_token(x_alert_token: str | None = Header(default=None)) -> None:
    """토큰이 설정돼 있고 요청 값과 같을 때만 통과한다. 설정이 비어 있으면 아무도 통과하지 못한다."""
    expected = settings.admin_alerts_token
    if not expected or not x_alert_token or not hmac.compare_digest(x_alert_token, expected):
        raise ApiError(403, "forbidden", "권한이 없어요")


def _item(row: AdminAlertLog) -> AlertItemOut:
    return AlertItemOut(
        key=row.key,
        rule=row.rule,
        severity=row.severity,
        message=row.message,
        menu=row.menu,
        created_at=row.created_at,
        acked_at=row.acked_at,
    )


@internal_router.post("/run", response_model=RunOut)
def run_checks(
    _: None = Depends(_check_token),
    db: Session = Depends(get_db),
) -> RunOut:
    """규칙을 한 번 점검한다. 설정이 꺼져 있으면 아무 일도 하지 않는다."""
    if not settings.admin_alerts_enabled:
        return RunOut(enabled=False, checked=0, created=0)
    checked, created = service.run_checks(db, datetime.now(UTC))
    return RunOut(enabled=True, checked=checked, created=created)


@admin_router.get("", response_model=AlertListOut)
def list_alerts(
    _: object = Depends(require_operator("admin")),
    db: Session = Depends(get_db),
) -> AlertListOut:
    rows, unacked = service.list_alerts(db)
    return AlertListOut(items=[_item(r) for r in rows], unacked=unacked)


@admin_router.post("/{key}/ack", response_model=AlertItemOut)
def ack_alert(
    key: str,
    _: object = Depends(require_operator("admin")),
    db: Session = Depends(get_db),
) -> AlertItemOut:
    row = service.ack(db, key, datetime.now(UTC))
    return _item(row)
