from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import KnowledgeChunk, KnowledgeItem


def add_item(db: Session, item: KnowledgeItem, chunks: list[KnowledgeChunk]) -> KnowledgeItem:
    db.add(item)
    db.flush()  # item.id 확정
    for chunk in chunks:
        chunk.item_id = item.id
        db.add(chunk)
    db.commit()
    return item


def get_item(db: Session, group_id: str, item_id: str) -> KnowledgeItem | None:
    return db.scalar(
        select(KnowledgeItem).where(KnowledgeItem.id == item_id, KnowledgeItem.group_id == group_id)
    )


def list_items(
    db: Session, group_id: str, kind_label: str | None = None, limit: int = 50
) -> list[KnowledgeItem]:
    q = select(KnowledgeItem).where(KnowledgeItem.group_id == group_id)
    if kind_label:
        q = q.where(KnowledgeItem.kind_label == kind_label)
    return list(
        db.scalars(
            q.order_by(KnowledgeItem.occurred_on.desc(), KnowledgeItem.created_at.desc()).limit(
                limit
            )
        )
    )


def candidate_chunks(
    db: Session,
    group_id: str,
    embedding_model: str,
    kind_label: str | None,
    date_from: date | None,
    date_to: date | None,
    include_sensitive: bool,
) -> list[tuple[KnowledgeChunk, KnowledgeItem]]:
    """검색 후보 조각. 가족 그룹이 다르거나 다른 모델로 만든 벡터는 처음부터 뺀다.

    TODO: PostgreSQL 에서는 이 점수 계산을 pgvector 의 `<=>` 거리와 인덱스로 DB 안에서 한다."""
    q = (
        select(KnowledgeChunk, KnowledgeItem)
        .join(KnowledgeItem, KnowledgeItem.id == KnowledgeChunk.item_id)
        .where(
            KnowledgeChunk.group_id == group_id,
            KnowledgeItem.group_id == group_id,
            KnowledgeChunk.embedding_model == embedding_model,
        )
    )
    if kind_label:
        q = q.where(KnowledgeItem.kind_label == kind_label)
    if date_from:
        q = q.where(KnowledgeItem.occurred_on >= date_from)
    if date_to:
        q = q.where(KnowledgeItem.occurred_on <= date_to)
    if not include_sensitive:
        q = q.where(KnowledgeItem.sensitivity != "sensitive")
    return [(c, i) for c, i in db.execute(q).all()]


def stale_chunks(
    db: Session, embedding_model: str, group_id: str | None = None
) -> list[KnowledgeChunk]:
    q = select(KnowledgeChunk).where(KnowledgeChunk.embedding_model != embedding_model)
    if group_id:
        q = q.where(KnowledgeChunk.group_id == group_id)
    return list(db.scalars(q))
