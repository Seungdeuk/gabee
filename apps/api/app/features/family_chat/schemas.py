from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    taken_at: datetime | None = (
        None  # 사진을 찍은 시각(UTC, 시간대 포함). null 이면 촬영일을 알 수 없어 보낸 날 기준이다(이미 올라간 사진은 모두 null). 문서는 항상 null
    )


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


class PhotoCheckItemOut(BaseModel):
    """업로더 본인의 "확인 필요" 사진 한 장. status: unsure(애매) | failed(판별 실패) | pending(처리 지연: 올린 지 15분 넘음)
    | excluded(`kind=excluded` 목록에서만: 내가 타임라인에서 뺀 사진)."""

    attachment_id: str
    thumb_url: str
    created_at: datetime
    taken_at: datetime | None = None
    status: Literal["unsure", "failed", "pending", "excluded"]
    # 실패 원인(사진 내용·글자는 담지 않는다): ocr_failed(글자 읽기 실패) | timeout(시간 초과) | ai_failed(AI 판별 오류) | stalled(오래 처리되지 않음) | null
    failure_kind: Literal["ocr_failed", "timeout", "ai_failed", "stalled"] | None = None
    can_retry: bool = False  # 지금 재검사(`POST /photos/{id}/recheck`)를 요청할 수 있는 사진인가(실패·처리 지연이고 횟수가 남음)
    retries_left: int = 0


class PhotoRecheckOut(BaseModel):
    """재검사 요청 결과. queued=true 면 이번 요청이 판별을 다시 맡겼고, false 면 이미 맡겨졌거나 처리 중이라 아무것도 바꾸지 않았다(같은 요청을 다시 보내도 같다).
    결과는 자동으로 `photo` 가 되지 않는다: 문서·애매·실패 중 하나로 끝나고, 일반 사진은 업로더가 직접 확인한다(D-13)."""

    status: Literal["pending"]
    queued: bool
    retries_left: int


class PhotoChecksOut(BaseModel):
    """내가 올린 사진 중 확인이 필요한 것(최신순). needs_review_count 는 전체 개수(`kind=excluded` 면 뺀 사진 전체 개수), next_before 는 다음 쪽을 받을 때 `before` 에 넣는 값(없으면 끝)."""

    items: list[PhotoCheckItemOut]
    needs_review_count: int
    next_before: int | None = None


class PhotoCheckIn(BaseModel):
    """일반 사진으로 확인. 문서·카드·서류가 찍힌 사진이면 확인하지 않는다. `acknowledge` 는 "가족 타임라인에 보이게 된다"는 안내를
    보고 확인했다는 뜻이라 반드시 true(서버가 강제한다). 이유 코드도 정해진 값 하나뿐이다."""

    to: Literal["photo"]
    reason: Literal["uploader_confirmed_general"]
    acknowledge: Literal[True]


class PhotoCheckOut(BaseModel):
    status: Literal["photo"]
    source: Literal["manual"]


class PhotoExcludeOut(BaseModel):
    """타임라인에서 뺐다(이미 뺀 사진에 다시 요청해도 같은 응답). 다시 넣으려면 일반 사진 확인(`POST /photos/{id}/check`)을 한다."""

    status: Literal["excluded"]
    source: Literal["manual"]


class TimelinePhotoOut(BaseModel):
    """가족 타임라인의 사진 한 장. display_at 은 촬영일(없으면 보낸 시각, `taken_at` 이 null 이면 "보낸 날 기준")이고 같은
    batch_id 묶음은 가장 이른 값으로 맞춘다. mine 은 내가 올린 사진(내가 뺄 수 있다)."""

    attachment_id: str
    message_id: int
    thumb_url: str
    display_at: datetime
    taken_at: datetime | None = None
    created_at: datetime
    batch_id: str | None = None
    mine: bool


class TimelineOut(BaseModel):
    """가족 타임라인(최신순). next_before 는 다음 쪽을 받을 때 `before` 에 그대로 넣는 값(없으면 끝)."""

    items: list[TimelinePhotoOut]
    next_before: str | None = None


class LibraryStateOut(BaseModel):
    """사진의 문서함 등록 여부. 확인하지 못하면 not_registered(성공으로 보이지 않게)."""

    state: Literal["registered", "not_registered"]


class ShareCreate(BaseModel):
    """공유 카드 보내기. 일정이면 ref 는 내 일정 id, 정산이면 월(YYYY-MM). 카드 내용은 서버가 읽어 만든다(클라이언트 값은 받지 않는다)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["event", "settlement"]
    ref: str = Field(min_length=1, max_length=32)
    room_id: str | None = Field(default=None, max_length=32)  # 없으면 가족 전체방


class ShareOut(BaseModel):
    """공유 카드. kind=event: title·date·start_time·end_time·place·kind·with_names.
    kind=settlement: month·remaining(내 남은 잔액, 받을 돈 +/보낼 돈 −)·lines(direction send|receive, name, amount)."""

    kind: Literal["event", "settlement"]
    payload: dict


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
    share: ShareOut | None = None  # 공유 카드 메시지의 내용(지운 메시지·카드가 아닌 메시지는 null)
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
