"""가족 채팅에 올린 첨부를 가족 공유 라이브러리(문서함)에 자동 등록하는 통로. family_chat 이 ai_assistant 내부를 직접 부르지 않도록
ai_assistant 가 시작할 때 처리 함수를 여기에 등록하고, family_chat 은 `document_posted`·`attachment_removed` 만 부른다.

등록 대상은 **가족 전체방에 올린 문서 첨부**뿐이다(1:1 방·사진은 부르는 쪽이 걸러서 넘기지 않는다). 처리 함수가 없으면(시험 등) 아무것도 하지 않는다.
어떤 오류도 부르는 쪽(채팅 전송·삭제)에 번지지 않는다."""

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# (group_id, user_id, attachment_id, filename, content_type, data) → 등록(백그라운드)
OnDocument = Callable[[str, str, str, str, str, bytes], None]
# (db, group_id, attachment_id) → 그 첨부에 연결된 기록 삭제
OnRemoved = Callable[[Session, str, str], None]

_on_document: OnDocument | None = None
_on_removed: OnRemoved | None = None


def register_handlers(on_document: OnDocument, on_removed: OnRemoved) -> None:
    """ai_assistant 가 시작할 때 부른다."""
    global _on_document, _on_removed
    _on_document, _on_removed = on_document, on_removed


def document_posted(
    group_id: str, user_id: str, attachment_id: str, filename: str, content_type: str, data: bytes
) -> None:
    """가족 전체방에 문서 첨부가 저장되면 부른다. 읽기·저장은 뒤에서 하고 실패해도 던지지 않는다."""
    if _on_document is None:
        return
    try:
        _on_document(group_id, user_id, attachment_id, filename, content_type, data)
    except Exception as exc:  # noqa: BLE001  채팅 전송을 깨면 안 된다(종류만 기록)
        logger.warning("chat library register failed error=%s", type(exc).__name__)


def attachment_removed(db: Session, group_id: str, attachment_id: str) -> None:
    """채팅 첨부(메시지)를 지우면 부른다. 그 첨부에서 만든 기록이 있으면 함께 지운다. 실패해도 던지지 않는다."""
    if _on_removed is None:
        return
    try:
        _on_removed(db, group_id, attachment_id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("chat library cleanup failed error=%s", type(exc).__name__)
