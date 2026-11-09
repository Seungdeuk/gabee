from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .schemas import PlayPersonOut

LIFE_RANGE = (1, 5)
SEC_RANGE = (1, 60)
WORD_MAX = 10


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


class PlayBombCheerIn(BaseModel):
    """관전 응원. 정해진 말 중에서 고른다."""

    text: str = Field(min_length=1, max_length=WORD_MAX)


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
    """채팅 한 줄. say 말함, timeout 시간 초과, cheer 관전 응원."""

    id: str
    kind: Literal["say", "timeout", "cheer"]
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
    cheers: list[str] = []  # 고를 수 있는 응원 말
    cheer_wait: float = 0  # 다음 응원까지 남은 초(0이면 보낼 수 있음)
    result: PlayBombResultOut | None = None
    close_at: datetime
