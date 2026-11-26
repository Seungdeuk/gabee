"""관리자 알림 업무 규칙: 점검(규칙 실행 → 새 알림 기록), 목록, 확인.

점검은 AI 를 쓰지 않는다. 기준을 넘은 것을 기록표에 한 줄 넣을 뿐이다.
규칙 하나가 실패해도 다른 규칙은 계속 돈다(로그에는 예외 종류만 남긴다).
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.shared.alert_rules import all_followups, all_rules
from app.shared.errors import not_found

from . import repository
from .models import AdminAlertLog

log = logging.getLogger(__name__)
LIST_LIMIT = 50
ACK_BY = "운영자"  # 확인한 사람은 사용자 id 가 아니라 고정 표시로 남긴다


def run_checks(db: Session, now: datetime) -> tuple[int, int]:
    """모든 규칙을 한 번 돌린다. (점검한 규칙 수, 새로 만든 알림 수)를 돌려준다."""
    checked = 0
    created = 0
    for name, check in all_rules():
        checked += 1
        try:
            findings = check(db, now)
        except Exception as exc:  # noqa: BLE001  한 규칙의 실패가 나머지 규칙을 막지 않게 한다
            log.warning("admin alert rule failed rule=%s error=%s", name, type(exc).__name__)
            continue
        for f in findings:
            row = AdminAlertLog(
                key=f.key,
                rule=f.rule,
                severity=f.severity,
                message=f.message,
                menu=f.menu,
                created_at=now,
            )
            if repository.insert_if_absent(db, row):
                created += 1
    db.commit()
    for (
        name,
        follow,
    ) in all_followups():  # 점검 결과를 저장한 뒤 이어서 할 일(관리자 초안 만들기 등)
        try:
            follow(db, now)
        except Exception as exc:  # noqa: BLE001  후속 작업의 실패가 점검 결과를 막지 않게 한다
            db.rollback()
            log.warning("admin alert followup failed name=%s error=%s", name, type(exc).__name__)
    return checked, created


def list_alerts(db: Session) -> tuple[list[AdminAlertLog], int]:
    """(목록, 확인 안 된 개수)."""
    return repository.list_rows(db, LIST_LIMIT), repository.unacked_count(db)


def ack(db: Session, key: str, now: datetime) -> AdminAlertLog:
    """알림을 확인 처리한다. 없는 키면 404. 이미 확인됐으면 기록을 바꾸지 않는다."""
    row = repository.get(db, key)
    if row is None:
        raise not_found("알림")
    repository.mark_acked(db, row, ACK_BY, now)
    return row
