"""가족 구성원이 가족을 나갈 때 다른 기능이 함께 정리할 일을 등록하는 통로. family_group 이 family_chat 등의 내부를 직접 부르지 않도록
각 기능이 시작할 때 정리 함수를 여기에 등록하고, family_group 은 `member_left` 만 부른다(`group_purge` 와 같은 방식).

- 정리 함수는 `(db, group_id, user_id) -> 커밋 뒤에 지울 디스크 파일 경로 목록`이고, **부르는 쪽 트랜잭션 안에서만** 일한다(커밋·롤백은 부르는 쪽).
- 정리 함수가 실패하면 예외를 그대로 던진다: 가족 나가기가 통째로 롤백돼 "가족은 나갔는데 1:1 방 참여는 남은" 반쪽 상태가 생기지 않는다.
- 등록된 함수가 없으면(시험 등) 아무것도 하지 않는다."""

from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

# (db, group_id, user_id) → 커밋 뒤에 지울 파일·폴더 경로
OnMemberLeft = Callable[[Session, str, str], list[Path]]

_handlers: list[OnMemberLeft] = []


def register(handler: OnMemberLeft) -> None:
    """각 기능이 시작할 때(모듈을 읽을 때) 부른다. 같은 함수를 두 번 등록해도 한 번만 부른다."""
    if handler not in _handlers:
        _handlers.append(handler)


def member_left(db: Session, group_id: str, user_id: str) -> list[Path]:
    """한 사람이 가족을 나갈 때 등록된 정리를 모두 실행하고, 커밋 뒤에 지워야 할 파일 경로를 모아 돌려준다. 커밋은 하지 않는다."""
    files: list[Path] = []
    for handler in _handlers:
        files += handler(db, group_id, user_id)
    return files
