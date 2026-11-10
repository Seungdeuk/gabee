from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .schemas import PlayPersonOut

LIFE_RANGE = (1, 5)
SEC_RANGE = (5, 60)  # 5초 밑이면 키보드가 올라오고 칠 틈이 없다
WORD_MAX = 10
CHEER_MAX = 20  # 응원 직접 쓰기 글자 수
CHAT_MAX = 50  # 탈락자 채팅 글자 수


class PlayBombStartIn(BaseModel):
    """방장이 게임을 시작할 때 정하는 규칙. 생명 1~5(기본 3), 차례당 시간 1~60초(기본 10)."""

    life: int = Field(default=3, ge=LIFE_RANGE[0], le=LIFE_RANGE[1])
    sec: int = Field(default=10, ge=SEC_RANGE[0], le=SEC_RANGE[1])


class PlayBombSayIn(BaseModel):
    """내 차례에 이어 말하는 한 단어나 짧은 구(10자까지)."""

    word: str = Field(min_length=1, max_length=WORD_MAX * 3)

    @field_validator("word")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = " ".join(v.split())  # 앞뒤·겹친 공백 정리
        if not v:
            raise ValueError("말을 써 주세요")
        if len(v) > WORD_MAX:
            raise ValueError(f"한 번에 {WORD_MAX}자까지 말할 수 있어요")
        return v


class PlayBombVoteStartIn(BaseModel):
    """판정 투표 신청: call 어라?, unfair 억울해요."""

    kind: Literal["call", "unfair"]


class PlayBombVoteIn(BaseModel):
    """투표: 찬성(맞아요) 또는 반대(아니에요)."""

    yes: bool


def _clean_text(v: str, limit: int) -> str:
    v = " ".join(v.split())  # 앞뒤·겹친 공백과 줄바꿈 정리
    if not v:
        raise ValueError("글자를 써 주세요")
    if len(v) > limit:
        raise ValueError(f"{limit}자까지 쓸 수 있어요")
    return v


class PlayBombCheerIn(BaseModel):
    """관전 응원. 정해진 말을 고르거나 직접 쓴다(20자까지)."""

    text: str = Field(min_length=1, max_length=CHEER_MAX * 3)

    @field_validator("text")
    @classmethod
    def _clean(cls, v: str) -> str:
        return _clean_text(v, CHEER_MAX)


class PlayBombChatIn(BaseModel):
    """탈락·구경하는 사람끼리 하는 채팅(50자까지)."""

    text: str = Field(min_length=1, max_length=CHAT_MAX * 3)

    @field_validator("text")
    @classmethod
    def _clean(cls, v: str) -> str:
        return _clean_text(v, CHAT_MAX)


class PlayBombPlayerOut(BaseModel):
    id: str
    name: str
    joined: bool  # 방에 들어와 있는지(아직 안 온 가족은 false)
    host: bool = False
    lives: int | None = None  # 게임 중에만. 방에 늦게 들어와 구경하는 사람은 None
    total: int | None = None
    out: bool = False  # 이번 판에서 탈락(또는 중간에 나감)
    spectator: bool = False  # 이번 판 시작 뒤에 들어와 구경하는 중


class PlayBombMessageOut(BaseModel):
    """채팅 한 줄. say 말함, timeout 시간 초과, cheer 관전 응원(모두에게 보임), chat 탈락·구경하는 사람끼리의 채팅(그 사람들에게만 보임), vote 판정 투표 결과."""

    id: str
    kind: Literal["say", "timeout", "cheer", "chat", "vote"]
    player: PlayPersonOut
    text: str
    ended: bool = False  # 이 말로 문장이 끝나 생명이 줄었다
    reason: Literal["end", "repeat"] | None = (
        None  # 문장이 끝난 까닭: end 문장을 끝냄, repeat 같은 말을 또 함
    )
    lost_life: bool = False  # 이 차례로 생명이 줄었다(문장 끝냄·시간 초과)
    out: bool = False  # 이 차례로 탈락했다
    at: datetime


class PlayBombTurnOut(BaseModel):
    player: PlayPersonOut
    seconds_left: float  # 응답을 만든 순간 기준 남은 초(화면은 이 값에서 줄여 나가고 다음 조회 때 다시 맞춘다)
    limit: float  # 이번 차례의 제한 시간(초): 차례가 지날수록 방에서 정한 시간보다 짧아진다
    deadline: datetime


class PlayBombVoteOut(BaseModel):
    """열려 있는 판정 투표. call 어라?(끝난 말인데 통과됐다), unfair 억울해요(끝난 말이 아닌데 탈락했다)."""

    kind: Literal["call", "unfair"]
    requester: PlayPersonOut
    target: PlayPersonOut  # 다투는 차례의 선수
    word: str  # 다투는 말
    seconds_left: float
    yes: int
    no: int
    waiting: int  # 아직 안 고른 사람(시간이 지나면 기권)
    my_choice: Literal["yes", "no"] | None = None
    can_vote: bool = False  # 내가 투표할 수 있는 사람이고 아직 안 골랐다


class PlayBombWordOut(BaseModel):
    text: str
    player: PlayPersonOut


class PlayBombSentenceOut(BaseModel):
    """한 문장: 이어 말한 말들(끝낸 말 포함)과 어떻게 끝났는가. end 문장을 끝냄, repeat 같은 말을 또 함, timeout 시간 초과, open 판이 끝날 때까지 이어가던 중."""

    words: list[PlayBombWordOut]
    end: Literal["end", "repeat", "timeout", "open"]
    ender: PlayPersonOut | None = None  # 끝낸(또는 시간을 넘긴) 사람


class PlayBombHistoryRoundOut(BaseModel):
    round_no: int
    life: int
    sec: int
    winner: PlayPersonOut | None = None
    longest_len: int
    sentences: list[PlayBombSentenceOut]


class PlayBombHistoryOut(BaseModel):
    """지난 방 기록: 끝난 판마다 이어 말한 문장. 방에 참여한 사람만 볼 수 있다."""

    id: str
    host: PlayPersonOut
    players: list[PlayPersonOut]
    closed: bool
    close_at: datetime
    rounds: list[PlayBombHistoryRoundOut]


class PlayBombRankOut(BaseModel):
    player: PlayPersonOut
    rank: int
    sub: str
    points: int


class PlayBombResultOut(BaseModel):
    round_no: int
    winner: PlayPersonOut | None = None
    longest_len: int
    prev_record: int | None = None  # 이전 가족 최고 기록(없으면 None)
    is_record: bool = False
    ranking: list[PlayBombRankOut]
    my_points: int | None = None
    maker_paid_before: bool = (
        False  # 방장이 이 방의 앞선 판에서 이미 문제 내기 +20을 받았다(이번 판 점수에는 없음)
    )


class PlayBombBriefOut(BaseModel):
    """방 목록의 한 줄: 홈의 "문장 폭탄"을 누르면 보이는 열린 방."""

    id: str
    phase: Literal["lobby", "playing", "finished"]
    host: PlayPersonOut
    players: list[PlayPersonOut]  # 지금 들어와 있는 사람(방장이 먼저, 그다음 들어온 순서)
    mine: bool  # 내가 들어와 있는 방
    life: int  # 이번(또는 마지막) 판 규칙. 로비에서는 기본값
    sec: int
    close_at: datetime


class PlayBombStateOut(BaseModel):
    id: str
    phase: Literal["lobby", "playing", "finished", "closed"]
    host: PlayPersonOut
    is_host: bool
    my_status: Literal["none", "player", "out", "spectator"]  # none = 아직 방에 안 들어옴
    players: list[PlayBombPlayerOut]
    round_no: int | None = None
    life: int  # 이번(또는 마지막) 판 규칙. 로비에서는 기본값
    sec: int
    turn: PlayBombTurnOut | None = None
    chain: int = 0  # 지금 문장을 이어가는 중인 말 개수
    messages: list[PlayBombMessageOut] = []
    vote: PlayBombVoteOut | None = None  # 열려 있는 판정 투표(없으면 None)
    can_call: bool = False  # 지금 "어라?"를 신청할 수 있다
    can_unfair: bool = False  # 지금 "억울해요"를 신청할 수 있다
    call_msg_id: str | None = None  # 방금 말(가장 최근 차례)의 채팅 줄 id: "어라?" 칩이 붙는 줄
    cheers: list[str] = []  # 고를 수 있는 응원 말
    cheer_wait: float = 0  # 다음 응원까지 남은 초(0이면 보낼 수 있음)
    chat_wait: float = 0  # 다음 채팅까지 남은 초(0이면 보낼 수 있음)
    result: PlayBombResultOut | None = None
    close_at: datetime
