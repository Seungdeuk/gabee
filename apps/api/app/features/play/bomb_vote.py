"""폭탄방 판정 투표(서버 메모리). 판이 끝나거나 새 판이 시작되면 버린다. DB 에는 아무것도 저장하지 않고, 결과만 마지막 차례 기록(끝 표시·생명)에 반영한다.

- 어라?(call): 살아있는 사람이 **다른 사람의** 방금 말에 "끝난 말인데 통과됐어요"라고 신청한다. 투표하는 사람은 살아있는 모두(신청자 자동 찬성).
- 억울해요(unfair): 내 마지막 말이 "끝난 말"로 판정돼 생명이 줄었거나 탈락한 **본인**이 신청한다(판이 계속되는 동안). 투표하는 사람은 살아있는 사람 중 본인을 뺀 모두.
- 한 사람이 한 판에 어라? 1번, 억울해요 1번. 한 번에 투표는 하나. 투표하는 동안 게임 시계는 멈춘다.
- 통과: 찬성이 반대보다 많고 찬성이 2표 이상. 투표 안 한 사람은 기권(표로 세지 않음). 같은 수면 기각.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime

VOTE_SEC = 10  # 투표 시간
MIN_YES = 2  # 통과에 필요한 찬성 최소 표
RESULT_KEEP = 20  # 방마다 기억하는 결과 줄 수
MIN_LEFT_AFTER = 3  # 투표가 끝나 시계가 이어질 때 남은 시간이 이보다 적으면 이만큼으로 올려 준다(바로 시간 초과 나는 것을 막음)

KIND_CALL = "call"
KIND_UNFAIR = "unfair"

TEXT = {
    (KIND_CALL, True): "투표 통과, 끝난 말로 바뀌었어요",
    (KIND_CALL, False): "투표 기각, 판정은 그대로예요",
    (KIND_UNFAIR, True): "투표 통과, 다시 게임에 돌아와요",
    (KIND_UNFAIR, False): "투표 기각, 탈락은 그대로예요",
}
# 억울해요를 탈락하지 않은 채(생명만 줄어든 채) 눌렀을 때의 결과 줄
TEXT_ALIVE = {
    True: "투표 통과, 생명이 돌아와요",
    False: "투표 기각, 판정은 그대로예요",
}


@dataclass
class Vote:
    kind: str
    round_no: int
    target_seq: int  # 다투는 차례(방금 기록된 마지막 차례)
    target_id: str  # 그 차례의 선수
    requester_id: str
    started: datetime
    deadline: datetime
    voters: set[str]  # 투표할 수 있는 사람(살아있는 사람)
    choices: dict[str, bool] = field(default_factory=dict)  # 선수 → 찬성(True)/반대(False)
    decided_at: datetime | None = None  # 투표할 사람이 모두 골랐을 때의 시각
    requester_out: bool = (
        True  # 억울해요를 누른 사람이 이미 탈락한 상태였는가(결과 문구가 달라진다)
    )

    def decided(self) -> bool:
        return self.voters <= set(self.choices)

    def counts(self) -> tuple[int, int]:
        yes = sum(1 for v in self.choices.values() if v)
        return yes, len(self.choices) - yes


@dataclass
class Result:
    seq: int
    round_no: int
    requester_id: str
    text: str
    at: datetime


@dataclass
class VoteBook:
    active: Vote | None = None
    used: set[tuple[int, str, str]] = field(default_factory=set)  # (판, 신청한 사람, 종류)
    results: list[Result] = field(default_factory=list)
    seq: int = 0


_books: dict[str, VoteBook] = {}
lock = threading.Lock()
_MAX_BOOKS = 200


def passes(yes: int, no: int) -> bool:
    return yes > no and yes >= MIN_YES


def book(play_id: str) -> VoteBook:
    """호출하는 쪽이 lock 을 잡고 부른다."""
    b = _books.get(play_id)
    if b is None:
        if len(_books) >= _MAX_BOOKS:  # 오래된 방부터 잊는다
            _books.pop(next(iter(_books)))
        b = _books[play_id] = VoteBook()
    return b


def active(play_id: str) -> Vote | None:
    with lock:
        b = _books.get(play_id)
        return b.active if b else None


def used(play_id: str, round_no: int, player_id: str, kind: str) -> bool:
    with lock:
        b = _books.get(play_id)
        return b is not None and (round_no, player_id, kind) in b.used


def drop_active(play_id: str) -> None:
    """판이 끝나면 열려 있던 투표를 버린다."""
    with lock:
        b = _books.get(play_id)
        if b:
            b.active = None


def drop(play_id: str) -> None:
    """새 판이 시작되면 투표 기록을 모두 새로 시작한다."""
    with lock:
        _books.pop(play_id, None)


def reset() -> None:
    """시험에서 투표 기록을 비운다."""
    with lock:
        _books.clear()
