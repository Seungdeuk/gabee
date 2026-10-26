"""일정 에이전트 입출력 형식. 메인 오케스트레이터(개인·가족 채팅)와 일정 화면 카드가 같은 형식을 쓴다.
형식은 메인 담당자와 협의해 바뀔 수 있다 — 호출하는 쪽은 `handler.handle` 만 알면 되게 둔다."""

from typing import Literal

from pydantic import BaseModel, Field

# 호출한 채팅의 종류. 읽을 수 있는 데이터가 이 값으로 정해진다(reader.py)
Channel = Literal["personal", "family"]

# 일정 요청의 종류. not_schedule 이면 일정 요청이 아니라는 뜻이라 메인이 직접 답한다
Intent = Literal["query", "recommend", "register", "edit", "delete", "check", "not_schedule"]
INTENTS: tuple[str, ...] = (
    "query",
    "recommend",
    "register",
    "edit",
    "delete",
    "check",
    "not_schedule",
)

# 채팅 안 카드 종류: 일정 목록 / 등록 완료 / 수정 확인 / 삭제 확인 / 추천
CardType = Literal["event_list", "registered", "edit_confirm", "delete_confirm", "suggestion"]


class AgentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    channel: Channel


class Card(BaseModel):
    type: CardType
    data: dict = Field(default_factory=dict)


class PendingAction(BaseModel):
    """수정·삭제 확인 카드가 들고 있는 실행 정보. 서버는 저장하지 않고(stateless) 확인 요청에 그대로 돌려받는다."""

    type: Literal["edit", "delete"]
    event_id: str
    changes: dict = Field(default_factory=dict)  # 수정일 때 바뀌는 값


class AgentResponse(BaseModel):
    intent: Intent
    text: str = ""
    cards: list[Card] = Field(default_factory=list)
    pending_action: PendingAction | None = None
