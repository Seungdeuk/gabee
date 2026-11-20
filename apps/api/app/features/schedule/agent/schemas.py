"""일정 에이전트 입출력 형식. 메인 오케스트레이터(개인·가족 채팅)와 일정 화면 카드가 같은 형식을 쓴다.
형식은 메인 담당자와 협의해 바뀔 수 있다 — 호출하는 쪽은 `handler.handle` 만 알면 되게 둔다."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# 호출한 채팅의 종류. 읽을 수 있는 데이터가 이 값으로 정해진다(reader.py)
Channel = Literal["personal", "family"]

# 일정 요청의 종류. not_schedule 이면 일정 요청이 아니라는 뜻이라 메인이 직접 답한다
Intent = Literal[
    "query",
    "recommend",
    "register",
    "edit",
    "delete",
    "check",
    "request",
    "habit",
    "not_schedule",
]
INTENTS: tuple[str, ...] = (
    "query",
    "recommend",
    "register",
    "edit",
    "delete",
    "check",
    "request",
    "habit",
    "not_schedule",
)

# 채팅 안 카드 종류: 일정 목록 / 등록 완료 / 공유 등록 확인 / 수정 확인 / 삭제 확인 / 추천 / 부탁 확인(보내기·받는 사람 바꾸기·취소) / 부탁 목록
CardType = Literal[
    "event_list",
    "registered",
    "register_confirm",
    "edit_confirm",
    "delete_confirm",
    "suggestion",
    "request_confirm",
    "request_list",
    "habit_confirm",
]


class Draft(BaseModel):
    """등록하려는 일정의 초안. 필수(제목·날짜)가 빠져 되물을 때 응답에 실어 주고, 사용자가 답하면 앱이 그대로 돌려보낸다.
    서버는 저장하지 않는다(stateless). 사용자가 보낸 값이므로 받을 때마다 다시 검증한다."""

    title: str = Field(default="", max_length=120)
    date: str = Field(default="", max_length=10)  # YYYY-MM-DD
    start_time: str = Field(default="", max_length=5)  # HH:MM
    end_time: str = Field(default="", max_length=5)
    kind: Literal[0, 1, 2] = 0  # 0 아직 모름, 1 약속, 2 할 일
    place: str = Field(default="", max_length=200)
    memo: str = Field(default="", max_length=1000)
    share_ids: list[str] = Field(
        default_factory=list, max_length=20
    )  # 공유할 사람(사용자가 요청했을 때만)
    asks: int = Field(default=0, ge=0, le=5)  # 지금까지 되물은 횟수
    # event 는 일정 등록 초안, request 는 부탁 보내기 초안(이때 share_ids 는 부탁받을 사람, kind 는 쓰지 않는다)
    mode: Literal["event", "request"] = "event"


class Choice(BaseModel):
    """수정·삭제 대상이 하나로 정해지지 않아 후보를 보여 주고 되물은 상태. 서버가 사용자별로 10분 기억하고(`choice.take`),
    앱이 돌려보내도 받는다. 답은 후보 안에서만 읽고, 받을 때마다 일정과 소유자를 다시 확인한다."""

    kind: Literal["edit", "delete", "request_edit", "request_cancel", "register"]
    event_ids: list[str] = Field(default_factory=list, max_length=20)  # 보여 준 후보
    changes: dict = Field(default_factory=dict)  # 수정일 때 바뀔 값(후보마다 다시 계산한다)
    past: bool = False  # 지난 일정 하나가 맞는지 묻는 중(삭제)
    members: bool = False  # 공유할 사람(같은 호칭의 가족이 여럿)을 묻는 중(수정)
    # kind 가 register 이면 changes 에 등록하려던 초안이 들어 있다(이미 있는 일정을 또 등록할지 묻는 중)
    # 앱이 체크박스 선택 카드로 보여 줄 후보: [{"id": 일정·부탁·구성원 id, "line": 한 줄 표기}]. 개인 채팅에서만 카드로 보인다
    options: list[dict] = Field(default_factory=list, max_length=20)


class AgentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    channel: Channel
    draft: Draft | None = None  # 직전 응답이 되물으며 준 초안(없으면 새 요청)
    choice: Choice | None = None  # 직전 응답이 후보를 보여 주며 되물은 상태(없으면 새 요청)


class Card(BaseModel):
    type: CardType
    data: dict = Field(default_factory=dict)


class PendingAction(BaseModel):
    """확인 카드가 들고 있는 실행 정보. 서버는 저장하지 않고(stateless) 확인 요청에 그대로 돌려받는다."""

    type: Literal[
        "edit",
        "delete",
        "register",
        "request_register",
        "request_edit",
        "request_cancel",
        "habit_check",
        "choice",
    ]
    event_id: str = ""  # 수정·삭제 대상(등록은 비어 있음). choice 이고 choice_kind 가 members 이면 공유를 바꿀 일정
    event_ids: list[str] = Field(
        default_factory=list, max_length=20
    )  # 여러 건 삭제의 대상(한 번에 10개까지). choice 이면 사용자가 체크한 일정·부탁·구성원 id
    # choice: 선택 카드에서 체크한 것을 바로 처리한다(확인 카드 없이). 무엇을 처리할지
    choice_kind: Literal["", "edit", "delete", "request_edit", "request_cancel", "members"] = ""
    changes: dict = Field(default_factory=dict)  # 수정일 때 바뀌는 값
    draft: Draft | None = None  # 등록(공유 확인)·부탁 보내기일 때 등록할 내용
    request_id: str = ""  # 부탁 받는 사람 바꾸기·취소 대상
    to_ids: list[str] = Field(default_factory=list, max_length=20)  # 부탁의 바뀐 뒤 받는 사람 전체
    # 데일리 체크 대신 누르기(habit_check): 대상 습관 id, mark(체크·횟수 더하기) / unmark(체크 취소·횟수 빼기), 횟수 습관에 더하거나 빼는 양
    habit_ids: list[str] = Field(default_factory=list, max_length=20)
    habit_op: Literal["", "mark", "unmark"] = ""
    amount: int = Field(default=1, ge=1, le=100)


class ConfirmRequest(BaseModel):
    """확인 카드의 버튼을 눌렀을 때. AI 를 부르지 않는다."""

    action: PendingAction
    share: bool = True  # 등록일 때 false 면 공유 대상을 빼고 내 일정만 만든다
    # 가족 채팅방의 @가비 카드에서 눌렀을 때 true. 공유 등록이면 결과를 가비 이름으로 방에 알린다(문장은 서버가 만든다)
    post_to_room: bool = False


class AgentResponse(BaseModel):
    intent: Intent
    text: str = ""
    cards: list[Card] = Field(default_factory=list)
    pending_action: PendingAction | None = None
    draft: Draft | None = None  # 되묻는 응답에만
    choice: Choice | None = None  # 수정·삭제 대상을 되묻는 응답에만


class SuggestionOut(BaseModel):
    id: str
    title: str
    kind: int
    start_date: str  # YYYY-MM-DD
    place: str
    later: bool = False  # "나중에"를 눌러 둔 추천


class SuggestionsRequest(BaseModel):
    """추천 요청. chat 은 앱이 보낸 개인 AI 채팅의 최근 7일 안 내 말이다(서버는 저장하지 않고 이번 생성에만 쓴다)."""

    chat: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=30)


class SuggestionsOut(BaseModel):
    """오늘의 추천 슬롯. state: ok(보여줄 추천이 있음) / exhausted(오늘 추천은 여기까지) / spent_empty(오늘 호출을 다 썼는데 받은 추천이 하나도 없음) /
    no_data(참고할 데이터가 없음) / filtered(데이터는 있는데 새로 만들 게 없음) / preparing(AI 호출 오류). can_refresh 는 새로고침이 의미 있는가.
    exhausted 는 state == "exhausted" 와 같다(예전 앱 호환)."""

    suggestions: list[SuggestionOut]
    exhausted: bool
    state: str = "ok"
    can_refresh: bool = True


class SuggestionLater(BaseModel):
    """ "나중에" 표시. later=true 면 나중에로, false 면 다시 대기로 되돌린다."""

    later: bool
