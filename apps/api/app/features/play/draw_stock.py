"""이게 뭐게 가비 추천의 단어별 그림 저장소. 한 번 그린 그림을 30일 동안 모든 가족이 다시 쓴다(단어당 최대 3종)."""

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import PlayDrawStock

STOCK_DAYS = 30  # 단어별 그림을 다시 쓰는 기간
STOCK_MAX = 3  # 단어당 쌓아 두는 그림 수


def stock_variants(db: Session, word: str, now: datetime) -> list[PlayDrawStock]:
    """word 의 저장된 그림 중 30일 안에 만든 것, 오래된 것부터."""
    since = now - timedelta(days=STOCK_DAYS)
    return list(
        db.scalars(
            select(PlayDrawStock)
            .where(PlayDrawStock.word == word, PlayDrawStock.created_at >= since)
            .order_by(PlayDrawStock.created_at, PlayDrawStock.id)
        )
    )


def add_variant(db: Session, word: str, strokes: list, now: datetime) -> PlayDrawStock:
    """그림을 저장한다. 30일이 지난 것은 먼저 지우고, 이미 3종이면 가장 오래된 것을 지운 뒤 넣는다."""
    db.execute(
        delete(PlayDrawStock).where(
            PlayDrawStock.word == word, PlayDrawStock.created_at < now - timedelta(days=STOCK_DAYS)
        )
    )
    fresh = stock_variants(db, word, now)
    for old in fresh[: max(0, len(fresh) - STOCK_MAX + 1)]:
        db.delete(old)
    row = PlayDrawStock(word=word, strokes=strokes, created_at=now)
    db.add(row)
    db.commit()
    return row
