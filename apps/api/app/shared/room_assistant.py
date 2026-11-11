"""가족 전체방에 가비 이름으로 글을 올리는 통로. 일정 같은 다른 기능이 가족 채팅(family_chat) 내부를 직접 부르지 않도록
family_chat 이 시작할 때 올리는 함수를 여기에 등록하고, 다른 기능은 `post` 만 부른다.

올리는 글은 부르는 쪽이 **서버에서 만든 문장**이어야 한다(사용자가 보낸 글을 그대로 가비 이름으로 올리는 입구는 두지 않는다)."""

from collections.abc import Callable

from sqlalchemy.orm import Session

_poster: Callable[[Session, str, str], int | None] | None = None


def register_poster(fn: Callable[[Session, str, str], int | None]) -> None:
    """가족 전체방에 글을 올리는 함수를 등록한다(family_chat 이 부른다). 반환은 올린 메시지 id."""
    global _poster
    _poster = fn


def post(db: Session, group_id: str, text: str) -> int | None:
    """가비 이름으로 가족 전체방에 글을 올리고 메시지 id 를 돌려준다. 올리는 함수가 없으면(시험 등) 아무것도 하지 않는다.
    group_id 는 호출한 쪽이 실제 구성원인지 확인한 값이어야 한다."""
    return _poster(db, group_id, text) if _poster is not None else None
