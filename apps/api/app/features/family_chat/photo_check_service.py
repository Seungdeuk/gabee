"""사진 판별 상태 업무 규칙(T05-b0-1). 자동 판별 결과는 shared/chat_library 통로로 받아 적고(ai_assistant 를 직접 부르지 않는다),
사람이 누른 "문서로 저장"은 상태를 `document`(수동)로 맞춘다. 업로더가 일반 사진으로 확인하는 기능은 b0-2 에서 만든다.

규칙(D-13): 자동 판별은 `photo` 를 만들지 못한다. 결과를 못 적거나 줄이 없으면 `pending` 그대로라 타임라인에 나오지 않는다."""

import logging

from sqlalchemy.orm import Session

from app.shared import chat_library
from app.shared.db import SessionLocal

from . import photo_check_repository as checks

logger = logging.getLogger(__name__)


def record_auto_result(group_id: str, attachment_id: str, status: str, error: str | None) -> None:
    """자동 판별 결과를 적는다(판별 스레드에서 부르므로 자기 세션을 연다). 이미 정해진 줄은 바꾸지 않는다."""
    with SessionLocal() as db:
        checks.record_auto(db, group_id, attachment_id, status, error)


def mark_document(db: Session, group_id: str, attachment_id: str) -> None:
    """사람이 "문서로 저장"을 눌렀을 때 상태를 문서(수동)로 맞춘다. 실패하면 던진다(상태가 `photo` 로 남은 채 저장되지 않게)."""
    checks.mark_document_manual(db, group_id, attachment_id)


chat_library.register_check_recorder(record_auto_result)
