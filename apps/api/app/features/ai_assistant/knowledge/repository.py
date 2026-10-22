from datetime import date

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, String, cast, literal, select
from sqlalchemy.orm import Session

from .embedding import cosine
from .models import EMBED_DIM, KnowledgeChunk, KnowledgeItem


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


def search_chunks(
    db: Session,
    group_id: str,
    embedding_model: str,
    query_vec: list[float],
    kind_label: str | None,
    date_from: date | None,
    date_to: date | None,
    include_sensitive: bool,
    limit: int = 60,
) -> list[tuple[KnowledgeChunk, KnowledgeItem, float]]:
    """질문 벡터와 가까운 조각을 점수(코사인 유사도, 클수록 가까움) 순으로 돌려준다.

    가족 그룹이 다르거나 다른 모델로 만든 벡터는 처음부터 뺀다. PostgreSQL 에서는 pgvector 의 `<=>`(코사인 거리)와
    HNSW 인덱스로 DB 안에서 가까운 조각만 가져오고, SQLite(테스트·로컬)에서는 후보를 가져와 파이썬에서 계산한다."""
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

    if db.get_bind().dialect.name == "postgresql":
        literal_vec = "[" + ",".join(f"{x:.6f}" for x in query_vec) + "]"
        distance = KnowledgeChunk.embedding.op("<=>", return_type=Float)(
            cast(literal(literal_vec, String), Vector(EMBED_DIM))
        )
        rows = db.execute(q.add_columns(distance.label("distance")).order_by(distance).limit(limit))
        return [(c, i, 1.0 - float(d)) for c, i, d in rows.all()]
    scored = [(c, i, cosine(query_vec, c.embedding)) for c, i in db.execute(q).all()]
    return sorted(scored, key=lambda row: row[2], reverse=True)[:limit]


def stale_chunks(
    db: Session, embedding_model: str, group_id: str | None = None
) -> list[KnowledgeChunk]:
    q = select(KnowledgeChunk).where(KnowledgeChunk.embedding_model != embedding_model)
    if group_id:
        q = q.where(KnowledgeChunk.group_id == group_id)
    return list(db.scalars(q))
