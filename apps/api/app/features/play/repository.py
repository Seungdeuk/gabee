from datetime import datetime

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from .constants import ASYNC_GAMES
from .models import PlayAnswer, PlayDraw, PlayItem, PlayPhoto, PlayQuiz, PlayScore


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
    """한 사람이 [start, end) 에 낸 비동기 놀이(낸 순서)."""
    return list(
        db.scalars(
            select(PlayItem)
            .where(
                PlayItem.maker_id == maker_id,
                PlayItem.game.in_(ASYNC_GAMES),
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
