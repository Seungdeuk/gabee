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


class ChatSource(BaseModel):
    """답이 근거로 쓴 기록. n 은 앱 출처 칩의 번호(1부터)."""

    n: int
    title: str
    item_id: str | None = None
    source_path: str | None = None


class ConfirmCardOut(BaseModel):
    """사용자가 버튼을 눌러야 실행되는 일정 요청(가족 공유 등록·수정·삭제). 앱은 `POST /schedule/agent/confirm` 에
    `{action: pending_action, share}` 를 보낸다. 서버는 돌려받은 pending_action 을 믿지 않고 처음부터 다시 검증한다."""

    kind: Literal["schedule"]
    action: Literal["register", "edit", "delete"]
    title: str  # 카드 제목(예: 수진, 서연에게 공유해서 등록할까요?)
    lines: list[str] = []  # 카드 본문(일정 제목·날짜, 바뀌는 내용)
    shared_with: list[str] = []  # register 일 때 공유 대상 이름(버튼 이름에 쓴다)
    pending_action: dict  # 확인 요청에 그대로 돌려보낸다


class ChatOut(BaseModel):
    reply: str
    source: str  # ai: AI 가 답함 | fallback: AI 를 쓸 수 없어 기본 안내를 보냄
    sources: list[ChatSource] = []
    proposals: list[
        ProposalOut
    ] = []  # 정산·돌봄 에이전트가 제안한 쓰기. 사용자가 확인해야 실행된다
    # room: 가족 채팅방에 올려도 되는 답 | private: 질문한 사람에게만 보여 줄 답(audience=me 이면 항상 private)
    visibility: Literal["room", "private"] = "private"
    private_reasons: list[str] = []  # private 인 이유(audience=room 일 때만. 예: 자녀 용돈 장부)
    confirm_cards: list[
        ConfirmCardOut
    ] = []  # 확인 버튼이 필요한 일정 요청(질문한 사람에게만 보인다)
    posted_message_id: int | None = (
        None  # visibility=room 이라 가비 이름으로 가족 전체방에 올린 메시지 id(없으면 올리지 않음)
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
