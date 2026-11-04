"""추천 문구 조회. 활성인 것 중에서 DB 가 무작위로 골라 준다(`ORDER BY random()`; 수백 줄이라 부담이 없다)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CheckSuggestion


def random_active(
    db: Session, category: int, limit: int, exclude_contents: list[str] | None = None
) -> list[CheckSuggestion]:
    """category 의 활성 추천 중 무작위 limit 개. exclude_contents 에 든 문구는 뺀다."""
    stmt = select(CheckSuggestion).where(
        CheckSuggestion.category == category, CheckSuggestion.active.is_(True)
    )
    if exclude_contents:
        stmt = stmt.where(CheckSuggestion.content.not_in(exclude_contents))
    return list(db.scalars(stmt.order_by(func.random()).limit(limit)))
