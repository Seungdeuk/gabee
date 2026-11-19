"""AI 추억 기능의 동의·삭제 사건을 다른 기능이 알려 주는 통로(`member_exit`·`chat_library` 와 같은 등록식).
family_chat·family_group 이 family_memory 내부를 직접 import 하지 않고 이 모듈만 부른다. 등록된 함수가 없으면(기능 꺼짐·시험) 아무 일도 하지 않는다.

사건 세 가지:
- `attachment_removed(db, group_id, attachment_id)`: 채팅 사진이 지워졌다(메시지 삭제). 채팅 삭제를 깨면 안 되므로 어떤 오류도 부르는 쪽에 번지지 않는다.
- `member_withdrawn(db, group_id, user_id)`: 업로더가 동의를 철회했거나 가족을 나갔다. 부르는 쪽 트랜잭션 안에서 일하고 오류는 그대로 던진다(철회·나가기가 통째로 롤백돼 반쪽 상태가 없다).
- `family_disabled(db, group_id)`: 가족 관리자가 기능을 껐다. 위와 같다.

등록 함수는 같은 입력으로 여러 번 불려도 결과가 같아야 한다(재시도 가능). 사진 내용·라벨·임베딩·파일 경로를 로그에 남기지 않는다."""

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

OnAttachmentRemoved = Callable[[Session, str, str], None]  # (db, group_id, attachment_id)
OnMemberWithdrawn = Callable[[Session, str, str], None]  # (db, group_id, user_id)
OnFamilyDisabled = Callable[[Session, str], None]  # (db, group_id)

_attachment_removed: list[OnAttachmentRemoved] = []
_member_withdrawn: list[OnMemberWithdrawn] = []
_family_disabled: list[OnFamilyDisabled] = []
OnPhotoExcluded = Callable[[Session, str, str], None]  # (db, group_id, attachment_id)
_photo_excluded: list[
    OnPhotoExcluded
] = []  # 업로더가 사진을 AI 분석에서 뺐다(PR3: 대기·진행 중인 작업을 막는다)


def register_photo_excluded(fn: OnPhotoExcluded) -> None:
    if fn not in _photo_excluded:
        _photo_excluded.append(fn)


def photo_excluded(db: Session, group_id: str, attachment_id: str) -> None:
    """사진별 제외 때 부른다. 오류는 그대로 던진다(커밋·롤백은 부르는 쪽)."""
    for fn in list(_photo_excluded):
        fn(db, group_id, attachment_id)


def register_attachment_removed(fn: OnAttachmentRemoved) -> None:
    if fn not in _attachment_removed:
        _attachment_removed.append(fn)


def register_member_withdrawn(fn: OnMemberWithdrawn) -> None:
    if fn not in _member_withdrawn:
        _member_withdrawn.append(fn)


def register_family_disabled(fn: OnFamilyDisabled) -> None:
    if fn not in _family_disabled:
        _family_disabled.append(fn)


def attachment_removed(db: Session, group_id: str, attachment_id: str) -> None:
    """채팅 사진 삭제 뒤에 부른다. 실패해도 던지지 않는다(종류만 기록)."""
    for fn in list(_attachment_removed):
        try:
            fn(db, group_id, attachment_id)
        except Exception as exc:  # noqa: BLE001  채팅 삭제를 깨면 안 된다
            logger.warning("memory attachment cleanup failed error=%s", type(exc).__name__)


def member_withdrawn(db: Session, group_id: str, user_id: str) -> None:
    """동의 철회·가족 나가기 때 부른다. 오류는 그대로 던진다(커밋·롤백은 부르는 쪽)."""
    for fn in list(_member_withdrawn):
        fn(db, group_id, user_id)


def family_disabled(db: Session, group_id: str) -> None:
    """가족 기능을 끌 때 부른다. 오류는 그대로 던진다(커밋·롤백은 부르는 쪽)."""
    for fn in list(_family_disabled):
        fn(db, group_id)
