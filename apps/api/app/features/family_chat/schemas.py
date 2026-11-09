from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    room_id: str | None = Field(default=None, max_length=32)  # 없으면 가족 전체방
    reply_to_id: int | None = Field(
        default=None,
        ge=1,
        le=2**31 - 1,
        description="답장할 메시지 id(같은 방의 지우지 않은 메시지)",
    )


class AttachmentOut(BaseModel):
    id: str
    kind: Literal["image", "file"]
    url: str  # 사진: 원본(최대 1600px JPEG) 경로, 문서: 내려받기 경로. 로그인이 필요하다
    thumb_url: str | None = None  # 사진: 목록용 작은 그림 경로, 문서: null
    width: int | None = None  # 문서는 null
    height: int | None = None  # 문서는 null
    batch_id: str | None = (
        None  # 한 번에 여러 장 올린 사진의 묶음 번호(같으면 한 묶음). 한 장짜리·문서는 null
    )
    filename: str | None = None  # 문서만(사용자가 올린 이름을 정리한 것)
    size_bytes: int | None = None
    content_type: str | None = None  # 문서만(허용 목록의 안전한 값)
    in_library: bool = False  # 사진이 이미 가족 문서함에 등록돼 있음(앱이 "문서로 저장" 버튼을 숨긴다). 메시지 목록에서만 채워진다


class ReplyOut(BaseModel):
    """답장이 가리키는 원본 메시지의 미리보기. 원본이 지워졌으면 deleted 이고 text 는 빈 문자열이다."""

    id: int
    user_name: str
    text: str  # 40자까지. 사진 메시지·지운 메시지는 빈 문자열
    deleted: bool = False
    has_attachment: bool = False  # 원본이 사진·문서 메시지
    attachment_kind: Literal["image", "file"] | None = None  # 원본 첨부의 종류(없으면 null)


class ReactionIn(BaseModel):
    emoji: str = Field(max_length=16, description="허용된 이모지 6개(❤️ 👍 😂 😮 😢 🙏) 중 하나")


class ReactionOut(BaseModel):
    emoji: str
    count: int  # 이 이모지를 누른 사람 수
    mine: bool  # 요청한 사람이 이 이모지를 눌렀는지


class LibrarySaveOut(BaseModel):
    """사진을 문서함에 저장한 결과: queued = 저장을 시작했다(읽는 데 시간이 걸린다), already = 이미 문서함에 있다."""

    status: Literal["queued", "already"]


class MessageOut(BaseModel):
    id: int
    user_id: str
    user_name: str
    text: str  # 사진 메시지는 빈 문자열
    created_at: datetime
    attachment: AttachmentOut | None = None
    is_assistant: bool = False  # 가비가 @가비 호출에 답해 올린 메시지(앱이 말풍선을 따로 그린다)
    reply_to: ReplyOut | None = (
        None  # 답장이면 원본 미리보기(방 목록의 마지막 메시지에는 붙지 않는다)
    )
    reactions: list[
        ReactionOut
    ] = []  # 많은 순(같으면 목록 순서). 방 목록의 마지막 메시지에는 채우지 않는다
    deleted: bool = False  # 보낸 사람이 지운 메시지. text 는 빈 문자열, attachment 는 null 이고 앱은 "삭제된 메시지입니다"를 보인다


class DeletedOut(BaseModel):
    message_ids: list[int]  # since 이후에 지워진 메시지 id(지운 순서, 최대 200개)
    server_time: datetime  # 이 응답을 만든 서버 시각. 다음 조회의 since 로 쓴다


class ReadMark(BaseModel):
    message_id: int = Field(ge=1, le=2**31 - 1)
    room_id: str | None = Field(default=None, max_length=32)  # 없으면 가족 전체방


class ReadPosition(BaseModel):
    last_read_message_id: int


class ReadStateOut(BaseModel):
    user_id: str
    last_read_message_id: int


class UnreadOut(BaseModel):
    unread: int
    last_read_message_id: int


class RoomOut(BaseModel):
    id: str
    kind: str  # family(가족 전체방) | direct(1:1)
    peer_user_id: str | None  # 1:1 방의 상대, 가족 전체방은 null
    last_message: MessageOut | None
    unread: int
    muted: bool = False  # 내가 이 방의 알림을 껐는지(기본 켜짐)
    peer_left: bool = False  # 1:1 방에서 상대가 방을 나가 읽기만 할 수 있음(peer_user_id 는 나간 사람, 새 메시지는 409 peer_left_room)


class MuteSet(BaseModel):
    muted: bool


class MuteOut(BaseModel):
    room_id: str
    muted: bool


class DirectRoomCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=32)


class TodoCreate(BaseModel):
    """created_by 같은 값은 받지 않는다(로그인한 사용자에서 유도)."""

    title: str = Field(min_length=1, max_length=120)
    assignee_id: str | None = Field(default=None, max_length=32)
    due_date: date | None = None
    source: Literal["manual", "chat"] = "manual"


class TodoUpdate(BaseModel):
    """보낸 항목만 바꾼다. assignee_id·due_date 에 null 을 보내면 비운다. done 은 완료(true)·되돌리기(false)."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    assignee_id: str | None = Field(default=None, max_length=32)
    due_date: date | None = None
    done: bool | None = None


class TodoOut(BaseModel):
    id: str
    title: str
    assignee_id: str | None
    due_date: date | None
    done: bool
    done_at: datetime | None
    done_by: str | None
    created_by: str
    source: str
    created_at: datetime
