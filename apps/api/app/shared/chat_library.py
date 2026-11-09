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

# (db, group_id, attachment_id) → 그 채팅 첨부가 아직 있는지(지운 메시지의 문서가 처리가 끝난 뒤 문서함에 남지 않게 확인한다)
Exists = Callable[[Session, str, str], bool]

_on_document: OnDocument | None = None
_on_removed: OnRemoved | None = None
_exists: Exists | None = None


def register_handlers(on_document: OnDocument, on_removed: OnRemoved) -> None:
    """ai_assistant 가 시작할 때 부른다."""
    global _on_document, _on_removed
    _on_document, _on_removed = on_document, on_removed


def register_exists(fn: Exists) -> None:
    """채팅 첨부가 아직 있는지 확인하는 함수를 등록한다(family_chat 이 시작할 때 부른다)."""
    global _exists
    _exists = fn


def attachment_exists(db: Session, group_id: str, attachment_id: str) -> bool:
    """채팅 첨부가 아직 있는지. 확인 함수가 없거나 확인하지 못하면 있는 것으로 본다(지우지 않는 쪽이 안전하다)."""
    if _exists is None:
        return True
    try:
        return _exists(db, group_id, attachment_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat library exists check failed error=%s", type(exc).__name__)
        return True


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


# (group_id, user_id, attachment_id, data, forced) → 사진 등록(백그라운드). forced 는 사용자가 "문서로 저장"을 눌러 판별을 건너뛴 경우
OnPhoto = Callable[[str, str, str, bytes, bool], None]
# (db, group_id, attachment_id) → 그 채팅 사진이 이미 문서함에 등록돼 있는지
IsRegistered = Callable[[Session, str, str], bool]
_on_photo: OnPhoto | None = None
_is_registered: IsRegistered | None = None


def register_photo_handler(on_photo: OnPhoto, is_registered: IsRegistered) -> None:
    """ai_assistant 가 시작할 때 사진 처리 함수와 "이미 등록했는지" 확인 함수를 등록한다."""
    global _on_photo, _is_registered
    _on_photo, _is_registered = on_photo, is_registered


def is_registered(db: Session, group_id: str, attachment_id: str) -> bool:
    """채팅 첨부가 이미 문서함에 등록돼 있는지. 확인 함수가 없거나 확인하지 못하면 아직 아닌 것으로 본다(다시 시도해도 한 번만 등록된다)."""
    if _is_registered is None:
        return False
    try:
        return _is_registered(db, group_id, attachment_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat library registered check failed error=%s", type(exc).__name__)
        return False


def photo_requested(group_id: str, user_id: str, attachment_id: str, data: bytes) -> None:
    """사용자가 사진의 "문서로 저장"을 눌렀을 때 부른다. 판별과 하루 상한을 건너뛰고 문서함에 등록한다(뒤에서 처리, 실패해도 던지지 않는다)."""
    if _on_photo is None:
        return
    try:
        _on_photo(group_id, user_id, attachment_id, data, True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat library photo save failed error=%s", type(exc).__name__)


def photo_posted(group_id: str, user_id: str, attachment_id: str, data: bytes) -> None:
    """가족 전체방에 사진이 저장되면 부른다. 문서 사진인지는 뒤에서 가려서(판별) 문서일 때만 등록한다. 실패해도 던지지 않는다."""
    if _on_photo is None:
        return
    try:
        _on_photo(group_id, user_id, attachment_id, data, False)
    except Exception as exc:  # noqa: BLE001  채팅 전송을 깨면 안 된다(종류만 기록)
        logger.warning("chat library photo failed error=%s", type(exc).__name__)


def attachment_removed(db: Session, group_id: str, attachment_id: str) -> None:
    """채팅 첨부(메시지)를 지우면 부른다. 그 첨부에서 만든 기록이 있으면 함께 지운다. 실패해도 던지지 않는다."""
    if _on_removed is None:
        return
    try:
        _on_removed(db, group_id, attachment_id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("chat library cleanup failed error=%s", type(exc).__name__)
