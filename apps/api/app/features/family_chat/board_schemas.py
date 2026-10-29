from datetime import datetime

from pydantic import BaseModel


class BoardItem(BaseModel):
    id: str  # 게시판 글 id(삭제에 쓴다)
    message_id: int  # 원본 메시지 id(채팅방에서 그 위치로 이동할 때 쓴다)
    text: str  # 올릴 때의 전체 본문 사본(원본이 지워져도 남는다)
    user_id: str  # 원본 메시지를 쓴 사람
    user_name: str
    message_created_at: datetime  # 원본 메시지를 보낸 시각
    posted_by: str  # 공지로 올린 사람(다시 올리면 마지막으로 올린 사람)
    posted_by_name: str
    posted_at: datetime  # 마지막으로 올린 시각(목록은 이 순서 최신순)
    is_current: bool  # 지금 채팅방 위 공지 바에 있는 공지인지(아니면 지난 공지)
    message_deleted: bool  # 원본 메시지를 보낸 사람이 지웠다(채팅에서 보기로 이동할 곳이 없다)


class BoardOut(BaseModel):
    items: list[BoardItem]  # 올린 시각 최신순
    next_before: (
        str | None
    )  # 더 오래된 글이 있으면 다음 쪽을 부를 때 before 로 넘길 값(없으면 null)
