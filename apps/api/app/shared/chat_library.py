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
# (db, group_id, attachment_ids) → 그중 이미 문서함에 등록된 것의 id(메시지 목록용, 한 번의 쿼리)
RegisteredIds = Callable[[Session, str, list[str]], set[str]]
_on_photo: OnPhoto | None = None
_is_registered: IsRegistered | None = None
_registered_ids: RegisteredIds | None = None


def register_photo_handler(
    on_photo: OnPhoto, is_registered: IsRegistered, registered_ids: RegisteredIds | None = None
) -> None:
    """ai_assistant 가 시작할 때 사진 처리 함수와 "이미 등록했는지" 확인 함수(한 장·여러 장)를 등록한다."""
    global _on_photo, _is_registered, _registered_ids
    _on_photo, _is_registered, _registered_ids = on_photo, is_registered, registered_ids


def registered_ids(db: Session, group_id: str, attachment_ids: list[str]) -> set[str]:
    """채팅 첨부들 중 이미 문서함에 등록된 것의 id. 확인 함수가 없거나 확인하지 못하면 빈 집합(버튼이 그대로 보일 뿐이다)."""
    if _registered_ids is None or not attachment_ids:
        return set()
    try:
        return _registered_ids(db, group_id, attachment_ids)
    except Exception as exc:  # noqa: BLE001  메시지 목록을 깨면 안 된다
        logger.warning("chat library registered ids failed error=%s", type(exc).__name__)
        return set()


def registered_state(db: Session, group_id: str, attachment_id: str) -> bool | None:
    """문서함 등록 여부를 세 갈래로: True(등록됨) / False(등록 안 됨) / None(확인하지 못함). 막는 방향 결정(fail-closed)에 쓴다:
    `is_registered` 는 못 확인하면 False 라 "문서가 아니다"로 읽힐 수 있어, 일반 사진 확정 같은 곳에는 쓰지 않는다.
    주의: 실패하면 세션을 `rollback` 한다 — 호출한 쪽에 커밋 전 쓰기가 없을 때만 부른다."""
    if _is_registered is None:
        return None
    try:
        return bool(_is_registered(db, group_id, attachment_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat library registered check failed error=%s", type(exc).__name__)
        try:
            db.rollback()  # 실패한 조회가 세션을 망가뜨린 채 남지 않게
        except Exception:  # noqa: BLE001
            pass
        return None


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


# (group_id, attachment_id, status, error) → 사진 판별 상태 기록(family_chat 이 시작할 때 등록한다). status 는 document|unsure|failed 만(일반 사진 확정은 자동으로 하지 않는다)
CheckRecorder = Callable[[str, str, str, str | None], bool | None]
_check_recorder: CheckRecorder | None = None


def register_check_recorder(fn: CheckRecorder) -> None:
    """사진 판별 결과를 적는 함수를 등록한다(family_chat 이 시작할 때 부른다)."""
    global _check_recorder
    _check_recorder = fn


def photo_judged(group_id: str, attachment_id: str, status: str, error: str | None = None) -> bool:
    """자동 판별이 끝났을 때 부른다. 못 적어도 던지지 않는다: 줄이 `pending` 으로 남아 사진은 타임라인에 나오지 않는다(안전한 쪽).
    돌려주는 값은 "문서함에 등록해도 되는가": 업로더가 이미 일반 사진(`photo`)으로 확인한 사진이면 False(등록하면 타임라인과 문서함 양쪽에
    있게 된다), 그 밖에는 True(못 적었을 때도 True: 문서는 숨기는 방향이라 기존 동작을 유지한다)."""
    if _check_recorder is None:
        return True
    try:
        return _check_recorder(group_id, attachment_id, status, error) is not False
    except Exception as exc:  # noqa: BLE001  판별 스레드를 깨면 안 된다(종류만 기록)
        logger.warning("chat library photo check record failed error=%s", type(exc).__name__)
        return True


_stale_counter: Callable[[], int] | None = None


def register_stale_counter(fn: Callable[[], int]) -> None:
    """오래도록 `pending` 으로 남은 사진 판별 수를 세는 함수를 등록한다(family_chat 이 시작할 때 부른다. 읽기 전용)."""
    global _stale_counter
    _stale_counter = fn


def stale_pending_photo_count() -> int | None:
    """15분 넘게 판별되지 않은 채팅 사진 수(서버가 판별 도중 죽었을 가능성의 신호). 세는 함수가 없거나 실패하면 None. 상태를 바꾸지 않는다."""
    if _stale_counter is None:
        return None
    try:
        return int(_stale_counter())
    except Exception as exc:  # noqa: BLE001  기동을 막으면 안 된다(종류만 기록)
        logger.warning("chat library stale count failed error=%s", type(exc).__name__)
        return None


def attachment_removed(db: Session, group_id: str, attachment_id: str) -> None:
    """채팅 첨부(메시지)를 지우면 부른다. 그 첨부에서 만든 기록이 있으면 함께 지운다. 실패해도 던지지 않는다."""
    if _on_removed is None:
        return
    try:
        _on_removed(db, group_id, attachment_id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("chat library cleanup failed error=%s", type(exc).__name__)
