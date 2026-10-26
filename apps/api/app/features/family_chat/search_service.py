"""대화 검색 업무 규칙: 카카오톡 돋보기처럼 글자 일치(키워드)만 한다. AI·외부 호출이 없고 질문·결과 글자를 로그에 남기지 않는다.

범위: 가족 전체방 + 내가 참여한 1:1 방(room_id 를 주면 그 방만, 권한이 없으면 404). 이 범위는 SQL 조건으로 들어간다."""

import unicodedata

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.errors import ApiError
from app.shared.rate_limit import FailureLimiter

from . import search_repository as srepo
from .models import FAMILY
from .search_schemas import SearchItem, SearchOut
from .service import resolve_room

MAX_QUERY_CHARS = 100
SEARCH_LIMIT = 30  # 사용자별 분당 검색 수
SEARCH_WINDOW_SECONDS = 60

search_limiter = FailureLimiter()  # 프로세스 메모리(shared/rate_limit.py 의 한계 참고)


_ALLOWED_CONTROLS = chr(9) + chr(10) + chr(13) + chr(11) + chr(12)  # 공백처럼 정리되는 제어문자


def normalize_query(q: str) -> str:
    """공백을 정리한다. NUL 을 포함한 그 밖의 제어문자(C0/C1)가 있으면 422 invalid_query(DB 를 부르기 전)."""
    q = q or ""
    if any(unicodedata.category(c) == "Cc" and c not in _ALLOWED_CONTROLS for c in q):
        raise ApiError(422, "invalid_query", "검색어에 쓸 수 없는 문자가 들어 있어요")
    return " ".join(q.split())


def _check_rate(user_id: str) -> None:
    key = f"chatsearch:{user_id}"
    wait = search_limiter.retry_after(key, SEARCH_LIMIT, SEARCH_WINDOW_SECONDS)
    if wait:
        raise ApiError(
            429,
            "too_many_searches",
            "검색을 너무 자주 했어요. 잠시 후 다시 해 주세요",
            headers={"Retry-After": str(wait)},
        )
    search_limiter.record(key)


def search(
    db: Session,
    user: User,
    group_id: str,
    q: str,
    room_id: str | None = None,
    limit: int = 20,
    before_id: int | None = None,
) -> SearchOut:
    query = normalize_query(q)
    if not 1 <= len(query) <= MAX_QUERY_CHARS:
        raise ApiError(422, "invalid_query", f"검색어는 1~{MAX_QUERY_CHARS}자로 입력해 주세요")
    _check_rate(user.id)
    if room_id is None:
        rooms = srepo.accessible_rooms(db, group_id, user.id)
    else:
        rooms = [resolve_room(db, user, group_id, room_id)]  # 권한이 없으면 404
    words = list(dict.fromkeys(query.split()))
    rows = srepo.search(db, group_id, rooms, words, limit + 1, before_id)
    more = len(rows) > limit
    rows = rows[:limit]

    family = next((r for r in rooms if r.kind == FAMILY), None)
    kinds = {r.id: r.kind for r in rooms}
    peers = srepo.peers(db, [r.id for r in rooms if r.kind != FAMILY], user.id)
    items = []
    for m, name in rows:
        rid = m.room_id or (family.id if family else "")  # 방이 없는 옛 메시지는 가족 전체방
        items.append(
            SearchItem(
                id=m.id,
                room_id=rid,
                room_kind=kinds[rid],
                peer_user_id=peers.get(rid),
                user_id=m.user_id,
                user_name=name,
                text=m.text,
                created_at=m.created_at.isoformat(),
            )
        )
    return SearchOut(items=items, next_before_id=items[-1].id if more and items else None)
