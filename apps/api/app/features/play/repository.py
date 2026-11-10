from datetime import datetime, timedelta

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from .constants import ASYNC_GAMES
from .models import (
    GAME_BOMB,
    PlayAnswer,
    PlayBombPlayer,
    PlayBombRound,
    PlayBombTurn,
    PlayDraw,
    PlayItem,
    PlayPhoto,
    PlayQuiz,
    PlayScore,
)
from .timeutil import local_day_start


def add(db: Session, *rows) -> None:
    db.add_all(rows)
    db.flush()


def get_item(db: Session, item_id: str, group_id: str, *, lock: bool = False) -> PlayItem | None:
    q = select(PlayItem).where(PlayItem.id == item_id, PlayItem.group_id == group_id)
    if lock:
        q = q.with_for_update()  # PostgreSQL 만, SQLite 는 무시
    return db.scalars(q).first()


def quiz_rows(db: Session, play_id: str) -> list[PlayQuiz]:
    return list(
        db.scalars(select(PlayQuiz).where(PlayQuiz.play_id == play_id).order_by(PlayQuiz.quiz_no))
    )


def get_draw(db: Session, play_id: str) -> PlayDraw | None:
    return db.get(PlayDraw, play_id)


def get_photo(db: Session, play_id: str) -> PlayPhoto | None:
    return db.get(PlayPhoto, play_id)


def answers_of(db: Session, play_id: str) -> list[PlayAnswer]:
    return list(
        db.scalars(
            select(PlayAnswer)
            .where(PlayAnswer.play_id == play_id)
            .order_by(PlayAnswer.answered_at, PlayAnswer.quiz_no, PlayAnswer.try_no)
        )
    )


def answers_of_many(db: Session, play_ids: list[str]) -> dict[str, list[PlayAnswer]]:
    out: dict[str, list[PlayAnswer]] = {pid: [] for pid in play_ids}
    if not play_ids:
        return out
    for a in db.scalars(
        select(PlayAnswer)
        .where(PlayAnswer.play_id.in_(play_ids))
        .order_by(PlayAnswer.answered_at, PlayAnswer.quiz_no, PlayAnswer.try_no)
    ):
        out[a.play_id].append(a)
    return out


def quiz_counts(db: Session, play_ids: list[str]) -> dict[str, int]:
    if not play_ids:
        return {}
    rows = db.execute(
        select(PlayQuiz.play_id, func.count())
        .where(PlayQuiz.play_id.in_(play_ids))
        .group_by(PlayQuiz.play_id)
    )
    return {pid: n for pid, n in rows}


def board_items(db: Session, group_id: str, since: datetime) -> list[PlayItem]:
    """진행 중이거나 since 이후에 닫힌 비동기 놀이(최근순)."""
    return list(
        db.scalars(
            select(PlayItem)
            .where(
                PlayItem.group_id == group_id,
                PlayItem.game.in_(ASYNC_GAMES),
                PlayItem.close_at >= since,
            )
            .order_by(PlayItem.created_at.desc())
        )
    )


def unsettled_closed_items(
    db: Session, group_id: str, now: datetime, since: datetime, reason: int
) -> list[PlayItem]:
    """닫혔고 아직 "문제 낸 사람" 점수 줄이 없는 놀이."""
    paid = exists().where(and_(PlayScore.play_id == PlayItem.id, PlayScore.reason == reason))
    return list(
        db.scalars(
            select(PlayItem)
            .where(
                PlayItem.group_id == group_id,
                PlayItem.game.in_(ASYNC_GAMES),
                PlayItem.close_at <= now,
                PlayItem.close_at >= since,
                ~paid,
            )
            .order_by(PlayItem.created_at)
        )
    )


def maker_items_between(
    db: Session, maker_id: str, start: datetime, end: datetime
) -> list[PlayItem]:
    """한 사람이 [start, end) 에 낸 놀이(낸 순서): 비동기 3종과, 한 판이라도 시작한 폭탄 방. 문제 내기 하루 한도를 센다."""
    return list(
        db.scalars(
            select(PlayItem)
            .where(
                PlayItem.maker_id == maker_id,
                or_(
                    PlayItem.game.in_(ASYNC_GAMES),
                    and_(
                        PlayItem.game == GAME_BOMB,
                        exists().where(PlayBombRound.play_id == PlayItem.id),
                    ),
                ),
                PlayItem.created_at >= start,
                PlayItem.created_at < end,
            )
            .order_by(PlayItem.created_at, PlayItem.id)
        )
    )


def scores_of(db: Session, play_id: str, player_id: str) -> list[PlayScore]:
    return list(
        db.scalars(
            select(PlayScore).where(PlayScore.play_id == play_id, PlayScore.player_id == player_id)
        )
    )


def maker_daily_rank(db: Session, item: PlayItem) -> int | None:
    """낸 날(한국 시간) 안에서 이 놀이가 몇 번째로 낸 것인지(1부터). 세지 않는 놀이면 None."""
    start = local_day_start(item.created_at)
    items = maker_items_between(db, item.maker_id, start, start + timedelta(days=1))
    for i, it in enumerate(items, start=1):
        if it.id == item.id:
            return i
    return None


def score_in_round_exists(db: Session, play_id: str, reason: int, round_no: int) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(PlayScore)
            .where(
                PlayScore.play_id == play_id,
                PlayScore.reason == reason,
                PlayScore.round_no == round_no,
            )
        )
        or 0
    ) > 0


def score_exists(db: Session, play_id: str, reason: int) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(PlayScore)
            .where(PlayScore.play_id == play_id, PlayScore.reason == reason)
        )
        or 0
    ) > 0


def scores_since(db: Session, group_id: str, since: datetime | None) -> list[PlayScore]:
    q = select(PlayScore).where(PlayScore.group_id == group_id)
    if since is not None:
        q = q.where(PlayScore.created_at >= since)
    return list(db.scalars(q))


def correct_counts(
    db: Session, group_id: str, since: datetime | None
) -> list[tuple[str, int, int]]:
    """(사람, 게임, 맞힌 개수). 골든벨은 맞힌 문항 수, 이게 뭐게·탐정단은 맞힌 문제 수다(힌트 상태 줄은 제외)."""
    q = (
        select(PlayAnswer.player_id, PlayItem.game, func.count())
        .join(PlayItem, PlayItem.id == PlayAnswer.play_id)
        .where(
            PlayItem.group_id == group_id,
            PlayAnswer.is_correct.is_(True),
            PlayAnswer.try_no >= 1,
        )
        .group_by(PlayAnswer.player_id, PlayItem.game)
    )
    if since is not None:
        q = q.where(PlayAnswer.answered_at >= since)
    return [(pid, game, n) for pid, game, n in db.execute(q)]


# ---------- 문장 폭탄방 ----------
def open_bomb_rooms(db: Session, group_id: str, now: datetime) -> list[PlayItem]:
    """가족의 열려 있는 폭탄방(닫히는 시각 전) 전부. 최근에 연 방이 먼저."""
    return list(
        db.scalars(
            select(PlayItem)
            .where(
                PlayItem.group_id == group_id, PlayItem.game == GAME_BOMB, PlayItem.close_at > now
            )
            .order_by(PlayItem.created_at.desc())
        )
    )


def my_open_bomb_room(
    db: Session, group_id: str, user_id: str, now: datetime, *, except_id: str | None = None
) -> PlayItem | None:
    """내가 선수로 들어와 있는 열린 폭탄방 한 개(없으면 None). except_id 방은 빼고 찾는다."""
    q = (
        select(PlayItem)
        .join(PlayBombPlayer, PlayBombPlayer.play_id == PlayItem.id)
        .where(
            PlayItem.group_id == group_id,
            PlayItem.game == GAME_BOMB,
            PlayItem.close_at > now,
            PlayBombPlayer.player_id == user_id,
        )
    )
    if except_id is not None:
        q = q.where(PlayItem.id != except_id)
    return db.scalars(q.order_by(PlayItem.created_at.desc())).first()


def bomb_players(db: Session, play_id: str) -> list[PlayBombPlayer]:
    return list(
        db.scalars(
            select(PlayBombPlayer)
            .where(PlayBombPlayer.play_id == play_id)
            .order_by(PlayBombPlayer.joined_at, PlayBombPlayer.player_id)
        )
    )


def bomb_player(db: Session, play_id: str, player_id: str) -> PlayBombPlayer | None:
    return db.get(PlayBombPlayer, (play_id, player_id))


def latest_bomb_round(db: Session, play_id: str) -> PlayBombRound | None:
    return db.scalars(
        select(PlayBombRound)
        .where(PlayBombRound.play_id == play_id)
        .order_by(PlayBombRound.round_no.desc())
    ).first()


def bomb_turns(db: Session, play_id: str, round_no: int) -> list[PlayBombTurn]:
    return list(
        db.scalars(
            select(PlayBombTurn)
            .where(PlayBombTurn.play_id == play_id, PlayBombTurn.round_no == round_no)
            .order_by(PlayBombTurn.turn_seq)
        )
    )


def bomb_rounds(db: Session, play_id: str) -> list[PlayBombRound]:
    return list(
        db.scalars(
            select(PlayBombRound)
            .where(PlayBombRound.play_id == play_id)
            .order_by(PlayBombRound.round_no)
        )
    )


def bomb_participants(db: Session, play_id: str) -> set[str]:
    """이 방에 들어왔거나 한 번이라도 말한 사람(중간에 나간 사람 포함)."""
    joined = db.scalars(select(PlayBombPlayer.player_id).where(PlayBombPlayer.play_id == play_id))
    spoke = db.scalars(select(PlayBombTurn.player_id).where(PlayBombTurn.play_id == play_id))
    return set(joined) | set(spoke)


def closed_bomb_rooms(db: Session, group_id: str, now: datetime, since: datetime) -> list[PlayItem]:
    """since 이후에 닫혔고 끝난 판이 하나라도 있는 폭탄 방(최근 닫힌 순)."""
    played = exists().where(
        and_(PlayBombRound.play_id == PlayItem.id, PlayBombRound.ended_at.is_not(None))
    )
    return list(
        db.scalars(
            select(PlayItem)
            .where(
                PlayItem.group_id == group_id,
                PlayItem.game == GAME_BOMB,
                PlayItem.close_at <= now,
                PlayItem.close_at >= since,
                played,
            )
            .order_by(PlayItem.close_at.desc())
        )
    )


def best_bomb_chain(db: Session, group_id: str, play_id: str, round_no: int) -> int | None:
    """이 판을 뺀, 가족의 끝난 폭탄 판 중 가장 긴 이어가기(없으면 None)."""
    return db.scalar(
        select(func.max(PlayBombRound.longest_len))
        .join(PlayItem, PlayItem.id == PlayBombRound.play_id)
        .where(
            PlayItem.group_id == group_id,
            PlayItem.game == GAME_BOMB,
            PlayBombRound.ended_at.is_not(None),
            ~and_(PlayBombRound.play_id == play_id, PlayBombRound.round_no == round_no),
        )
    )
