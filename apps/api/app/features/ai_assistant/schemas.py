from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.shared.llm.schemas import ProposalOut


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)
    # 가비의 답이 개인용(private)이라 질문한 사람에게만 보였던 턴. 방에서 부른 요청의 앞 대화에 이런 턴이 있으면 이번 답도 방에 올리지 않는다
    private: bool = False


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=10)  # 앞 대화(오래된 것부터)
    # me: 나와 가비의 대화(기본). room: 가족 채팅방에서 @가비 로 부른 것 — 답을 방에 올려도 되는지 서버가 정해 visibility 로 알려 준다
    audience: Literal["me", "room"] = "me"
    # audience=room 일 때 @가비 를 부른 1:1 방 id. 있으면 답을 그 1:1 방에 올린다(참가자 본인·상대가 가족일 때만). 없으면 가족 전체방.
    room_id: str | None = Field(default=None, max_length=32)


class ChatSource(BaseModel):
    """답이 근거로 쓴 기록. n 은 앱 출처 칩의 번호(1부터)."""

    n: int
    title: str
    item_id: str | None = None
    source_path: str | None = None


class ShareItemOut(BaseModel):
    id: str
    line: str  # 제목·날짜·시간만(관련 구성원 이름은 넣지 않는다)


class ConfirmCardOut(BaseModel):
    """사용자가 버튼을 눌러야 실행되는 일정 요청(가족 공유 등록·수정·삭제). 앱은 `POST /schedule/agent/confirm` 에
    `{action: pending_action, share}` 를 보낸다. 서버는 돌려받은 pending_action 을 믿지 않고 처음부터 다시 검증한다."""

    kind: Literal["schedule"]
    action: Literal[
        "register",
        "edit",
        "delete",
        "request_register",
        "request_edit",
        "request_cancel",
        "habit_check",
        "share_select",
        "choice_select",
    ]
    title: str  # 카드 제목(예: 수진, 서연에게 공유해서 등록할까요?)
    lines: list[str] = []  # 카드 본문(일정 제목·날짜, 바뀌는 내용)
    shared_with: list[str] = []  # register 일 때 공유 대상 이름(버튼 이름에 쓴다)
    pending_action: dict  # 확인 요청에 그대로 돌려보낸다(share_select 는 비어 있다)
    # share_select: 가족방 @가비 조회 결과 중 방에 공유할 후보. 앱이 고른 줄만 질문한 사람 이름의 일반 메시지로 보낸다
    # choice_select: 개인 채팅에서 대상이 여럿일 때 체크박스로 고르는 후보(삭제·수정 일정, 공유할 가족, 부탁 취소). 앱은 체크한 id 를
    # pending_action.event_ids 에 넣어 `POST /schedule/agent/confirm` 에 보내고, 서버는 확인 카드 없이 바로 처리한다
    items: list[ShareItemOut] = []
    ok_label: str = ""  # choice_select 의 실행 버튼 이름(삭제·바꾸기·공유·부탁 취소)


class ShareConfirmIn(BaseModel):
    """토큰에 보낼 글(최대 500자)이 들어 있어 정산 확인보다 길다."""

    token: str = Field(min_length=10, max_length=16000)


class MemoryOut(BaseModel):
    """가비의 기억 한 줄."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    text: str
    created_at: datetime


class MemoryIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)  # 공백 정리 뒤 200자 안인지는 서버가 다시 본다


class MemoriesOut(BaseModel):
    items: list[MemoryOut]


class MemoryDeletedOut(BaseModel):
    deleted: int


class WebSource(BaseModel):
    """답이 인용한 웹 페이지."""

    title: str
    url: str


class ChatOut(BaseModel):
    reply: str
    source: str  # ai: AI 가 답함 | fallback: AI 를 쓸 수 없어 기본 안내를 보냄
    sources: list[ChatSource] = []
    web_sources: list[WebSource] = []  # 답이 인용한 웹 페이지(웹 검색을 썼을 때만)
    proposals: list[
        ProposalOut
    ] = []  # 정산·돌봄 에이전트가 제안한 쓰기. 사용자가 확인해야 실행된다
    # room: 가족 채팅방에서 부른 답(모두에게 공유, audience=room 이면 항상 room) | private: 나와 가비의 개인 대화(audience=me 이면 항상 private)
    visibility: Literal["room", "private"] = "private"
    private_reasons: list[str] = []  # 이전 앱 호환용(항상 빈 목록)
    confirm_cards: list[
        ConfirmCardOut
    ] = []  # 확인 버튼이 필요한 일정 요청(질문한 사람에게만 보인다)
    posted_message_id: int | None = (
        None  # audience=room 이라 가비 이름으로 방(가족 전체방 또는 1:1 방)에 올린 메시지 id(개인 대화이거나 답이 비면 없음)
    )


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    size: int
    status: str  # received | analyzed | needs_review | failed


class FileStatusOut(FileOut):
    title: str | None = None
    kind_label: str | None = None
    description: str | None = None
    message: str | None = None
    doubts: list[str] = []  # 글자 인식이 흐려서 사용자에게 맞는지 물어볼 줄(가려진 상태의 글)
    needs_description: bool = False  # 글자가 안 읽힌 사진인데 사용자가 단 설명이 아직 없다


class DescriptionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=200)  # 앞뒤 공백을 뺀 길이로 센다


class PhotoOut(BaseModel):
    id: str
    filename: str
    size: int
    status: str
    created_at: datetime


class NudgeOut(BaseModel):
    id: str  # 챙길 일 id
    kind: str  # propose(일정으로 잡을까요) | urgent(미리 알림) | followup(하셨나요)
    text: str


class NudgesOut(BaseModel):
    nudges: list[NudgeOut]
    message: str = ""  # 여러 개를 한 번에 보기 좋게 묶은 말(하나뿐이면 그 문장, 없으면 빈 문자열). 앱은 이것만 보여 준다


class ReminderSettingsIn(BaseModel):
    enabled: bool


class ReminderSettingsOut(BaseModel):
    enabled: bool
