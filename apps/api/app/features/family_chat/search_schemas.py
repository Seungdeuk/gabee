from typing import Literal

from pydantic import BaseModel


class SearchItem(BaseModel):
    id: int
    room_id: str  # 메시지가 있는 방(가족 전체방 메시지도 그 방 id)
    room_kind: Literal["family", "direct"]
    peer_user_id: str | None  # 1:1 방의 상대(가족 전체방은 null)
    user_id: str
    user_name: str
    text: str
    created_at: str  # ISO 8601


class SearchOut(BaseModel):
    items: list[SearchItem]  # 최신순
    next_before_id: int | None  # 더 있으면 마지막 항목의 id(다음 쪽은 before_id 로), 없으면 null
