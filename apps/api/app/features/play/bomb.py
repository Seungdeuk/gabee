"""가족 놀이터 문장 폭탄방: 실시간 턴제 게임. 화면이 1초쯤마다 방 상태를 물어보는 폴링 방식이라 서버는 요청을 받을 때 시간을 계산한다.

- 방: 가족마다 열린 방은 하나. 방장이 만들고 가족이 들어온다. 닫히는 시각(`close_at`)은 로비 1시간, 판이 시작되면 시작 + 2시간(상한),
  판이 끝나면 끝난 시각 + 1시간, 방장이 닫으면 그 순간이다.
- 판: 생명(1~5)·차례당 시간(1~60초)을 방장이 시작할 때 정한다. 진행 순서는 방장 → 들어온 순서. 판이 시작된 뒤에 들어온 사람은 관전한다.
- 차례: 내 차례에 한 단어나 짧은 구(10자)를 이어 말한다. 지금까지 이어 말한 문장 전체를 Kiwi 로 판정해서 문장이 끝났으면 생명 -1,
  제한 시간을 넘기면 생명 -1(시간 초과). 생명을 잃으면 문장은 새로 시작한다. 생명이 0이 되면 탈락이고 마지막 1명이 이긴다.
- 시간 초과는 별도 배치 없이 방 상태를 조회하거나 말할 때 계산해서 기록한다(마감 방식은 다른 놀이와 같다).
- 점수: 판마다 참여한 사람 +10, 우승 +30. 방장은 참여 점수 없이 방마다 한 번 문제 내기 +20(하루 한도 안에서).
- 관전 응원은 서버 메모리에만 둔다(저장하지 않음). 한 사람이 5초에 한 번만 보낼 수 있다(난타 방지).
"""

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.family_group import repository as group_repo
from app.features.family_group.models import User
from app.shared.errors import ApiError, bad_request, not_found

from . import repository
from .bomb_judge import is_ended, is_repeat
from .bomb_schemas import (
    LIFE_RANGE,
    SEC_RANGE,
    PlayBombMessageOut,
    PlayBombPlayerOut,
    PlayBombRankOut,
    PlayBombResultOut,
    PlayBombStartIn,
    PlayBombStateOut,
    PlayBombTurnOut,
)
from .constants import DAILY_MAKE_LIMIT, POINT_BOMB_WIN, POINT_JOIN, POINT_MAKE
from .models import (
    GAME_BOMB,
    REASON_BOMB_WIN,
    REASON_JOIN,
    REASON_MAKE,
    PlayBombPlayer,
    PlayBombRound,
    PlayBombTurn,
    PlayItem,
    PlayScore,
)
from .schemas import PlayPersonOut
from .timeutil import aware

LOBBY_HOURS = 1  # 방을 만든 뒤 아무도 시작하지 않으면 닫힌다
PLAY_HOURS = 2  # 한 판의 상한
AFTER_HOURS = 1  # 판이 끝난 뒤 "한 판 더"를 기다리는 시간
MIN_PLAYERS = 2
CHEER_COOLDOWN_SEC = 5  # 응원 난타 방지
CHEER_KEEP = 40  # 방마다 기억하는 응원 수
CHEERS = ("힘내요", "아슬아슬", "끝내지 마!")
MESSAGE_KEEP = 200  # 상태에 담는 채팅 줄 수


def _now() -> datetime:
    return datetime.now(UTC)


def _person(u: User | None) -> PlayPersonOut:
    return PlayPersonOut(id=u.id, name=u.name) if u else PlayPersonOut(id="", name="알 수 없음")


# ---------- 관전 응원(서버 메모리) ----------
@dataclass
class _Cheer:
    seq: int
    round_no: int
    player_id: str
    text: str
    at: datetime


@dataclass
class _CheerBook:
    items: list[_Cheer] = field(default_factory=list)
    last: dict[str, datetime] = field(default_factory=dict)
    seq: int = 0


_cheer_books: dict[str, _CheerBook] = {}
_cheer_lock = threading.Lock()
_MAX_BOOKS = 200


def _cheer_book(play_id: str) -> _CheerBook:
    book = _cheer_books.get(play_id)
    if book is None:
        if len(_cheer_books) >= _MAX_BOOKS:  # 오래된 방부터 잊는다
            _cheer_books.pop(next(iter(_cheer_books)))
        book = _cheer_books[play_id] = _CheerBook()
    return book


def reset_cheers() -> None:
    """시험에서 응원 기록을 비운다."""
    with _cheer_lock:
        _cheer_books.clear()


# ---------- 판 상태 계산 ----------
@dataclass
class _Game:
    order: list[str]  # 이번 판에 참여한 사람(방장 → 들어온 순서)
    lives: dict[str, int]
    alive: list[str]
    cur: str | None  # 지금 차례
    deadline: datetime | None
    chain: int  # 지금 문장을 이어가는 중인 말 개수
    longest: int  # 이 판의 최장 이어가기
    words: list[str]  # 지금 문장의 말들
    last_seq: int


def _derive(
    item: PlayItem, rnd: PlayBombRound, players: list[PlayBombPlayer], turns: list[PlayBombTurn]
) -> _Game:
    started = aware(rnd.started_at)
    present = [p for p in players if aware(p.joined_at) <= started]
    order = [
        p.player_id
        for p in sorted(present, key=lambda p: (p.player_id != item.maker_id, aware(p.joined_at)))
    ]
    for t in turns:  # 판 도중 나간 사람도 기록에는 남아 있다
        if t.player_id not in order:
            order.append(t.player_id)
    lives = {pid: rnd.life for pid in order}
    chain = longest = 0
    words: list[str] = []
    for t in turns:
        lives[t.player_id] = t.life
        if t.is_say and not t.is_end:
            chain += 1
            words.append(t.word or "")
        else:  # 문장을 끝냈거나 시간이 지나 생명을 잃으면 문장을 새로 시작한다
            longest = max(longest, chain)
            chain, words = 0, []
    longest = max(longest, chain)
    alive = [pid for pid in order if lives[pid] > 0]
    last = turns[-1] if turns else None
    cur = _next_alive(order, lives, last.player_id if last else None)
    base = aware(last.created_at) if last else started
    deadline = base + timedelta(seconds=rnd.sec) if cur else None
    return _Game(
        order, lives, alive, cur, deadline, chain, longest, words, last.turn_seq if last else 0
    )


def _next_alive(order: list[str], lives: dict[str, int], after: str | None) -> str | None:
    start = order.index(after) + 1 if after in order else 0
    for k in range(len(order)):
        pid = order[(start + k) % len(order)]
        if lives[pid] > 0:
            return pid
    return None


def _finish(
    db: Session, item: PlayItem, rnd: PlayBombRound, g: _Game, when: datetime, winner: str | None
) -> None:
    """판을 끝내고 점수를 준다. 한 번만 불린다(ended_at 이 이미 있으면 아무것도 안 함)."""
    if rnd.ended_at is not None:
        return
    rnd.ended_at = when
    rnd.winner_id = winner
    rnd.longest_len = g.longest
    with _cheer_lock:
        _cheer_books.pop(item.id, None)  # 응원은 저장하지 않는다: 판이 끝나면 버린다
    item.close_at = when + timedelta(hours=AFTER_HOURS)
    # 방장은 참여 점수 대신 방마다 한 번 "문제 내기" +20 을 받는다(하루 한도 안에서). 참여 횟수는 세도록 0점 줄을 남긴다.
    rows = [(pid, REASON_JOIN, 0 if pid == item.maker_id else POINT_JOIN) for pid in g.order]
    if item.maker_id in g.order and not repository.score_exists(db, item.id, REASON_MAKE):
        rank = repository.maker_daily_rank(db, item)
        if rank is not None and rank <= DAILY_MAKE_LIMIT:
            rows.append((item.maker_id, REASON_MAKE, POINT_MAKE))
    if winner:
        rows.append((winner, REASON_BOMB_WIN, POINT_BOMB_WIN))
    repository.add(
        db,
        *[
            PlayScore(
                group_id=item.group_id,
                player_id=pid,
                play_id=item.id,
                game=GAME_BOMB,
                round_no=rnd.round_no,
                reason=reason,
                points=points,
                created_at=when,
            )
            for pid, reason, points in rows
        ],
    )


def _settle_time(db: Session, item: PlayItem, rnd: PlayBombRound, now: datetime) -> None:
    """제한 시간이 지난 차례를 시간 초과로 기록한다. 아무도 조회하지 않은 사이 여러 차례가 지났어도 순서대로 채운다."""
    players = repository.bomb_players(db, item.id)
    while rnd.ended_at is None:
        turns = repository.bomb_turns(db, item.id, rnd.round_no)
        g = _derive(item, rnd, players, turns)
        if len(g.alive) <= 1:  # 보통은 마지막 차례에서 이미 끝나 있다
            when = aware(turns[-1].created_at) if turns else aware(rnd.started_at)
            _finish(db, item, rnd, g, when, g.alive[0] if g.alive else None)
            return
        if now >= aware(item.close_at):  # 한 판의 상한: 우승자 없이 끝낸다
            _finish(db, item, rnd, g, aware(item.close_at), None)
            return
        if g.cur is None or g.deadline is None or now < g.deadline:
            return
        repository.add(
            db,
            PlayBombTurn(
                play_id=item.id,
                round_no=rnd.round_no,
                turn_seq=g.last_seq + 1,
                player_id=g.cur,
                is_say=False,
                word=None,
                is_end=False,
                life=g.lives[g.cur] - 1,
                created_at=g.deadline,
            ),
        )


# ---------- 방 ----------
def _load(db: Session, group_id: str, room_id: str, *, lock: bool) -> PlayItem:
    item = repository.get_item(db, room_id, group_id, lock=lock)
    if item is None or item.game != GAME_BOMB:
        raise not_found("방")
    return item


def _settled(db: Session, item: PlayItem, now: datetime) -> PlayBombRound | None:
    rnd = repository.latest_bomb_round(db, item.id)
    if rnd is not None and rnd.ended_at is None:
        _settle_time(db, item, rnd, now)
    return rnd


def current_room(db: Session, user: User, group_id: str) -> PlayBombStateOut | None:
    now = _now()
    item = repository.open_bomb_room(db, group_id, now)
    if item is None:
        return None
    return get_room(db, user, group_id, item.id)


def create_room(db: Session, user: User, group_id: str) -> PlayBombStateOut:
    now = _now()
    members = group_repo.members(db, group_id)
    if len(members) < MIN_PLAYERS:
        raise bad_request("no_recipient", "함께 할 가족이 아직 없어요")
    if repository.open_bomb_room(db, group_id, now) is not None:
        raise ApiError(409, "room_open", "이미 열려 있는 폭탄방이 있어요")
    item = PlayItem(
        group_id=group_id,
        game=GAME_BOMB,
        maker_id=user.id,
        player_ids=[],
        close_at=now + timedelta(hours=LOBBY_HOURS),
        created_at=now,
    )
    repository.add(db, item)
    repository.add(db, PlayBombPlayer(play_id=item.id, player_id=user.id, joined_at=now))
    db.commit()
    return build_state(db, item, user, members, now)


def get_room(db: Session, user: User, group_id: str, room_id: str) -> PlayBombStateOut:
    now = _now()
    item = _load(db, group_id, room_id, lock=True)  # 시간 초과를 기록할 수 있어 잠그고 읽는다
    _settled(db, item, now)
    db.commit()
    return build_state(db, item, user, group_repo.members(db, group_id), now)


def join_room(db: Session, user: User, group_id: str, room_id: str) -> PlayBombStateOut:
    now = _now()
    item = _load(db, group_id, room_id, lock=True)
    _settled(db, item, now)
    if aware(item.close_at) <= now:
        raise ApiError(409, "closed", "이미 닫힌 방이에요")
    if repository.bomb_player(db, item.id, user.id) is None:
        repository.add(db, PlayBombPlayer(play_id=item.id, player_id=user.id, joined_at=now))
    db.commit()
    return build_state(db, item, user, group_repo.members(db, group_id), now)


def leave_room(db: Session, user: User, group_id: str, room_id: str) -> PlayBombStateOut:
    """방을 나간다. 방장은 나갈 수 없고(방 닫기를 쓴다), 게임 중에 나가면 그 사람은 탈락한다."""
    now = _now()
    item = _load(db, group_id, room_id, lock=True)
    if item.maker_id == user.id:
        raise ApiError(409, "host_cannot_leave", "방장은 나갈 수 없어요. 방을 닫아 주세요")
    rnd = _settled(db, item, now)
    row = repository.bomb_player(db, item.id, user.id)
    if row is not None:
        if rnd is not None and rnd.ended_at is None:
            players = repository.bomb_players(db, item.id)
            turns = repository.bomb_turns(db, item.id, rnd.round_no)
            g = _derive(item, rnd, players, turns)
            if user.id in g.alive:  # 게임 중에 나가면 남은 생명을 모두 잃는다
                repository.add(
                    db,
                    PlayBombTurn(
                        play_id=item.id,
                        round_no=rnd.round_no,
                        turn_seq=g.last_seq + 1,
                        player_id=user.id,
                        is_say=False,
                        word=None,
                        is_end=False,
                        life=0,
                        created_at=now,
                    ),
                )
                _after_turn(db, item, rnd, players, now)
        db.delete(row)
    db.commit()
    return build_state(db, item, user, group_repo.members(db, group_id), now)


def close_room(db: Session, user: User, group_id: str, room_id: str) -> PlayBombStateOut:
    now = _now()
    item = _load(db, group_id, room_id, lock=True)
    if item.maker_id != user.id:
        raise ApiError(403, "not_host", "방장만 방을 닫을 수 있어요")
    rnd = _settled(db, item, now)
    if rnd is not None and rnd.ended_at is None:
        raise ApiError(409, "in_game", "게임이 끝난 뒤에 방을 닫을 수 있어요")
    if aware(item.close_at) > now:
        item.close_at = now
    db.commit()
    return build_state(db, item, user, group_repo.members(db, group_id), now)


def start_round(
    db: Session, user: User, group_id: str, room_id: str, body: PlayBombStartIn
) -> PlayBombStateOut:
    """게임 시작 / 한 판 더. 방에 들어온 사람이 2명 이상이어야 한다."""
    now = _now()
    item = _load(db, group_id, room_id, lock=True)
    if item.maker_id != user.id:
        raise ApiError(403, "not_host", "방장만 시작할 수 있어요")
    if aware(item.close_at) <= now:
        raise ApiError(409, "closed", "이미 닫힌 방이에요")
    rnd = _settled(db, item, now)
    if rnd is not None and rnd.ended_at is None:
        raise ApiError(409, "in_game", "이미 게임 중이에요")
    if aware(item.close_at) <= now:  # 상한이 지나 방금 닫힘
        raise ApiError(409, "closed", "이미 닫힌 방이에요")
    players = repository.bomb_players(db, item.id)
    if len(players) < MIN_PLAYERS:
        raise ApiError(409, "need_players", "2명부터 시작할 수 있어요")
    repository.add(
        db,
        PlayBombRound(
            play_id=item.id,
            round_no=(rnd.round_no + 1) if rnd else 1,
            life=body.life,
            sec=body.sec,
            started_at=now,
        ),
    )
    item.close_at = now + timedelta(hours=PLAY_HOURS)
    with _cheer_lock:
        _cheer_books.pop(item.id, None)  # 새 판에서는 응원도 새로 시작
    db.commit()
    return build_state(db, item, user, group_repo.members(db, group_id), now)


def _after_turn(
    db: Session, item: PlayItem, rnd: PlayBombRound, players: list[PlayBombPlayer], now: datetime
) -> None:
    """방금 기록한 차례 뒤에 한 명만 남았으면 판을 끝낸다."""
    db.flush()
    turns = repository.bomb_turns(db, item.id, rnd.round_no)
    g = _derive(item, rnd, players, turns)
    if len(g.alive) <= 1:
        _finish(db, item, rnd, g, now, g.alive[0] if g.alive else None)


def say(db: Session, user: User, group_id: str, room_id: str, word: str) -> PlayBombStateOut:
    now = _now()
    item = _load(db, group_id, room_id, lock=True)
    rnd = _settled(db, item, now)
    if rnd is None or rnd.ended_at is not None:
        db.commit()
        raise ApiError(409, "not_playing", "지금은 게임 중이 아니에요")
    players = repository.bomb_players(db, item.id)
    turns = repository.bomb_turns(db, item.id, rnd.round_no)
    g = _derive(item, rnd, players, turns)
    if g.cur != user.id:
        db.commit()  # 위에서 기록한 시간 초과는 남긴다
        raise ApiError(409, "not_your_turn", "지금은 내 차례가 아니에요")
    # 이번 문장에서 이미 나온 말을 또 하거나 대답을 되풀이하면 문장을 끝낸 것과 같이 생명이 줄어든다
    ended = is_repeat(word, g.words) or is_ended(
        " ".join([*g.words, word])
    )  # 문장은 지금까지 이어 말한 전체를 본다
    repository.add(
        db,
        PlayBombTurn(
            play_id=item.id,
            round_no=rnd.round_no,
            turn_seq=g.last_seq + 1,
            player_id=user.id,
            is_say=True,
            word=word,
            is_end=ended,
            life=g.lives[user.id] - (1 if ended else 0),
            created_at=now,
        ),
    )
    _after_turn(db, item, rnd, players, now)
    db.commit()
    return build_state(db, item, user, group_repo.members(db, group_id), now)


def cheer(db: Session, user: User, group_id: str, room_id: str, text: str) -> PlayBombStateOut:
    """탈락했거나 구경하는 사람이 응원을 보낸다. 한 사람이 5초에 한 번만."""
    now = _now()
    if text not in CHEERS:
        raise bad_request("invalid_cheer", "정해진 응원 중에서 골라 주세요")
    item = _load(db, group_id, room_id, lock=True)
    rnd = _settled(db, item, now)
    db.commit()
    if rnd is None or rnd.ended_at is not None:
        raise ApiError(409, "not_playing", "게임 중에만 응원할 수 있어요")
    players = repository.bomb_players(db, item.id)
    if repository.bomb_player(db, item.id, user.id) is None:
        raise ApiError(403, "not_in_room", "방에 들어와 있어야 응원할 수 있어요")
    g = _derive(item, rnd, players, repository.bomb_turns(db, item.id, rnd.round_no))
    if user.id in g.alive:
        raise ApiError(403, "still_playing", "게임 중인 사람은 응원할 수 없어요")
    with _cheer_lock:
        book = _cheer_book(item.id)
        last = book.last.get(user.id)
        if last is not None and (wait := CHEER_COOLDOWN_SEC - (now - last).total_seconds()) > 0:
            raise ApiError(
                429,
                "cheer_cooldown",
                f"응원은 {CHEER_COOLDOWN_SEC}초에 한 번만 보낼 수 있어요",
                headers={"Retry-After": str(max(1, round(wait)))},
            )
        book.last[user.id] = now
        book.seq += 1
        book.items.append(_Cheer(book.seq, rnd.round_no, user.id, text, now))
        del book.items[:-CHEER_KEEP]
    return build_state(db, item, user, group_repo.members(db, group_id), now)


# ---------- 보기 ----------
def _messages(
    item: PlayItem, rnd: PlayBombRound, turns: list[PlayBombTurn], by_id: dict[str, User]
) -> list[PlayBombMessageOut]:
    out: list[PlayBombMessageOut] = []
    words: list[str] = []  # 지금 문장의 말들(까닭을 다시 가려내려고 기록을 처음부터 따라간다)
    for t in turns:
        lost = t.is_end or not t.is_say
        reason = None
        if t.is_end:
            reason = "repeat" if is_repeat(t.word or "", words) else "end"
        if lost:
            words = []
        elif t.is_say:
            words.append(t.word or "")
        out.append(
            PlayBombMessageOut(
                id=f"t{t.turn_seq}",
                kind="say" if t.is_say else "timeout",
                player=_person(by_id.get(t.player_id)),
                text=t.word or "",
                ended=t.is_end,
                reason=reason,
                lost_life=lost,
                out=lost and t.life <= 0,
                at=aware(t.created_at),
            )
        )
    with _cheer_lock:
        cheers = [c for c in _cheer_book(item.id).items if c.round_no == rnd.round_no]
    out.extend(
        PlayBombMessageOut(
            id=f"c{c.seq}",
            kind="cheer",
            player=_person(by_id.get(c.player_id)),
            text=c.text,
            at=c.at,
        )
        for c in cheers
    )
    out.sort(key=lambda m: m.at)
    return out[-MESSAGE_KEEP:]


def _result(
    db: Session,
    item: PlayItem,
    rnd: PlayBombRound,
    turns: list[PlayBombTurn],
    g: _Game,
    by_id: dict[str, User],
    my_id: str,
) -> PlayBombResultOut:
    out_at: dict[str, int] = {}  # 탈락한 차례 번호(작을수록 먼저 탈락)
    for t in turns:
        if t.life <= 0 and t.player_id not in out_at:
            out_at[t.player_id] = t.turn_seq
    winner = rnd.winner_id
    losers = sorted((pid for pid in g.order if pid != winner), key=lambda pid: -out_at.get(pid, 0))
    first_out = sorted(out_at, key=lambda pid: out_at[pid])  # 먼저 탈락한 순서
    ranking = []
    ordered = ([winner] if winner else []) + losers
    make_paid = repository.score_in_round_exists(db, item.id, REASON_MAKE, rnd.round_no)
    for i, pid in enumerate(ordered, start=1):
        # 방장: 참여 점수 없음, 이 판에서 문제 내기 +20 을 받았으면 그 점수
        points = (POINT_MAKE if make_paid else 0) if pid == item.maker_id else POINT_JOIN
        if pid == winner:
            sub = f"생명 {g.lives.get(pid, 0)}개 · 끝까지 살아남음"
            points += POINT_BOMB_WIN
        else:
            n = first_out.index(pid) + 1 if pid in first_out else len(g.order)
            sub = f"{n}번째로 탈락" if pid in out_at else "게임이 끝나 마무리"
        ranking.append(
            PlayBombRankOut(player=_person(by_id.get(pid)), rank=i, sub=sub, points=points)
        )
    prev = repository.best_bomb_chain(db, item.group_id, item.id, rnd.round_no)
    longest = rnd.longest_len
    return PlayBombResultOut(
        round_no=rnd.round_no,
        winner=_person(by_id.get(winner)) if winner else None,
        longest_len=longest,
        prev_record=prev,
        is_record=longest > 0 and longest > (prev or 0),
        ranking=ranking,
        my_points=next((r.points for r in ranking if r.player.id == my_id), None),
    )


def build_state(
    db: Session, item: PlayItem, user: User, members: list[User], now: datetime
) -> PlayBombStateOut:
    by_id = {m.id: m for m in members}
    rows = repository.bomb_players(db, item.id)
    rnd = repository.latest_bomb_round(db, item.id)
    playing = rnd is not None and rnd.ended_at is None
    closed = aware(item.close_at) <= now and not playing
    phase = "closed" if closed else "playing" if playing else "finished" if rnd else "lobby"
    turns = repository.bomb_turns(db, item.id, rnd.round_no) if rnd else []
    g = _derive(item, rnd, rows, turns) if rnd else None

    joined_ids = {r.player_id for r in rows}
    ordered = [
        r.player_id
        for r in sorted(rows, key=lambda r: (r.player_id != item.maker_id, aware(r.joined_at)))
    ]
    players: list[PlayBombPlayerOut] = []
    for pid in ordered:
        u = by_id.get(pid)
        entry = PlayBombPlayerOut(
            id=pid, name=u.name if u else "알 수 없음", joined=True, host=pid == item.maker_id
        )
        if g is not None and phase in ("playing", "finished"):
            if pid in g.lives:
                entry.lives, entry.total, entry.out = g.lives[pid], rnd.life, g.lives[pid] <= 0
            else:
                entry.spectator = True
        players.append(entry)
    for m in members:  # 아직 안 들어온 가족
        if m.id not in joined_ids:
            players.append(PlayBombPlayerOut(id=m.id, name=m.name, joined=False))

    if user.id not in joined_ids:
        my_status = "none"
    elif g is not None and phase == "playing":
        my_status = (
            "spectator"
            if user.id not in g.lives
            else ("out" if g.lives[user.id] <= 0 else "player")
        )
    else:
        my_status = "player"

    turn = None
    if playing and g and g.cur and g.deadline:
        turn = PlayBombTurnOut(
            player=_person(by_id.get(g.cur)),
            seconds_left=max(0.0, round((g.deadline - now).total_seconds(), 2)),
            deadline=g.deadline,
        )

    with _cheer_lock:
        last = _cheer_book(item.id).last.get(user.id) if item.id in _cheer_books else None
    wait = max(0.0, CHEER_COOLDOWN_SEC - (now - last).total_seconds()) if last else 0.0

    result = None
    if (
        phase in ("finished", "closed")
        and rnd is not None
        and rnd.ended_at is not None
        and g is not None
    ):
        result = _result(db, item, rnd, turns, g, by_id, user.id)
    return PlayBombStateOut(
        id=item.id,
        phase=phase,
        host=_person(by_id.get(item.maker_id)),
        is_host=item.maker_id == user.id,
        my_status=my_status,
        players=players,
        round_no=rnd.round_no if rnd else None,
        life=rnd.life if rnd else 3,
        sec=rnd.sec if rnd else 10,
        turn=turn,
        chain=g.chain if g else 0,
        messages=_messages(item, rnd, turns, by_id) if rnd else [],
        cheers=list(CHEERS),
        cheer_wait=round(wait, 2),
        result=result,
        close_at=aware(item.close_at),
    )


__all__ = ["LIFE_RANGE", "SEC_RANGE", "CHEERS", "CHEER_COOLDOWN_SEC"]
