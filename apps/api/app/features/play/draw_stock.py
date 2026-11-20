"""이게 뭐게 가비 추천의 단어별 그림 저장소. 한 번 그린 그림을 모든 가족이 계속 다시 쓴다(단어당 최대 3종, 기간 제한 없음)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PlayDrawStock

STOCK_MAX = 3  # 단어당 쌓아 두는 그림 수


def stock_variants(db: Session, word: str, now: datetime) -> list[PlayDrawStock]:
    """word 의 저장된 그림, 오래된 것부터. now 는 호출부와 맞추려고 받는다(기간 제한이 없어 쓰지 않는다)."""
    return list(
        db.scalars(
            select(PlayDrawStock)
            .where(PlayDrawStock.word == word)
            .order_by(PlayDrawStock.created_at, PlayDrawStock.id)
        )
    )


def add_variant(db: Session, word: str, strokes: list, now: datetime) -> PlayDrawStock:
    """그림을 저장한다. 이미 3종이면 가장 오래된 것을 지운 뒤 넣는다."""
    stored = stock_variants(db, word, now)
    for old in stored[: max(0, len(stored) - STOCK_MAX + 1)]:
        db.delete(old)
    row = PlayDrawStock(word=word, strokes=strokes, created_at=now)
    db.add(row)
    db.commit()
    return row
