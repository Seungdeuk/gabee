from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Float,
    String,
    cast,
    delete,
    distinct,
    exists,
    false,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from .embedding import cosine
from .models import EMBED_DIM, KnowledgeChunk, KnowledgeItem, KnowledgeItemRead


def add_item(db: Session, item: KnowledgeItem, chunks: list[KnowledgeChunk]) -> KnowledgeItem:
    db.add(item)
    db.flush()  # item.id 확정
    for chunk in chunks:
        chunk.item_id = item.id
        db.add(chunk)
    db.commit()
    return item


def replace_chunks(db: Session, item: KnowledgeItem, chunks: list[KnowledgeChunk]) -> KnowledgeItem:
    """기록의 조각을 새 것으로 바꾼다(이전 조각 삭제와 새 조각 저장이 한 번에 반영된다)."""
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.item_id == item.id))
    for chunk in chunks:
        chunk.item_id = item.id
        db.add(chunk)
    db.commit()
    return item


def items_containing(
    db: Session, group_id: str, needle: str, limit: int = 20
) -> list[KnowledgeItem]:
    """본문에 needle 이 들어 있는 기록(최근 순)."""
    q = select(KnowledgeItem).where(
        KnowledgeItem.group_id == group_id, KnowledgeItem.body_md.contains(needle, autoescape=True)
    )
    return list(db.scalars(q.order_by(KnowledgeItem.created_at.desc()).limit(limit)))


def delete_item(db: Session, item: KnowledgeItem) -> None:
    """기록과 그 조각·읽음 기록을 함께 지운다."""
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.item_id == item.id))
    db.execute(delete(KnowledgeItemRead).where(KnowledgeItemRead.item_id == item.id))
    db.delete(item)
    db.commit()


def mark_read(db: Session, item_id: str, user_id: str) -> None:
    """이 사용자가 기록을 읽었다고 남긴다. 이미 있으면 아무것도 하지 않는다(동시에 불려도 안전)."""
    if db.get(KnowledgeItemRead, (item_id, user_id)) is not None:
        return
    db.add(KnowledgeItemRead(item_id=item_id, user_id=user_id))
    try:
        db.commit()
    except IntegrityError:  # 동시에 같은 읽음이 먼저 저장됨
        db.rollback()


def seen_item_ids(db: Session, user_id: str, item_ids: list[str]) -> set[str]:
    """주어진 기록 중 이 사용자가 읽은 것의 id (쿼리 한 번)."""
    if not item_ids:
        return set()
    return set(
        db.scalars(
            select(KnowledgeItemRead.item_id).where(
                KnowledgeItemRead.user_id == user_id, KnowledgeItemRead.item_id.in_(item_ids)
            )
        )
    )


def path_in_use(db: Session, group_id: str, source_path: str) -> bool:
    """같은 원본 파일을 가리키는 다른 기록이 남아 있는지(같은 파일을 두 번 올린 경우)."""
    return (
        db.scalar(
            select(KnowledgeItem.id)
            .where(KnowledgeItem.group_id == group_id, KnowledgeItem.source_path == source_path)
            .limit(1)
        )
        is not None
    )


def get_by_attachment(db: Session, group_id: str, attachment_id: str) -> KnowledgeItem | None:
    """이 채팅 첨부에서 만든 기록(이 가족의 것만). 없으면 None."""
    return db.scalar(
        select(KnowledgeItem).where(
            KnowledgeItem.group_id == group_id,
            KnowledgeItem.source_attachment_id == attachment_id,
        )
    )


def registered_attachment_ids(db: Session, group_id: str, attachment_ids: list[str]) -> set[str]:
    """주어진 채팅 첨부 중 이 가족의 기록이 이미 있는 것의 id(한 번의 쿼리)."""
    if not attachment_ids:
        return set()
    return set(
        db.scalars(
            select(KnowledgeItem.source_attachment_id).where(
                KnowledgeItem.group_id == group_id,
                KnowledgeItem.source_attachment_id.in_(attachment_ids),
            )
        )
    )


def get_item(db: Session, group_id: str, item_id: str) -> KnowledgeItem | None:
    return db.scalar(
        select(KnowledgeItem).where(KnowledgeItem.id == item_id, KnowledgeItem.group_id == group_id)
    )


def list_items(
    db: Session,
    group_id: str,
    kind_label: str | None = None,
    limit: int = 50,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    created_by: list[str] | None = None,
) -> list[KnowledgeItem]:
    """created_from 이상, created_to 미만(둘 다 UTC aware datetime)인 기록만 거른다. 안 주면 거르지 않는다.
    created_by 를 주면 그 사용자들이 올린 기록만 본다(빈 목록이면 결과 없음)."""
    q = select(KnowledgeItem).where(KnowledgeItem.group_id == group_id)
    if kind_label:
        q = q.where(KnowledgeItem.kind_label == kind_label)
    if created_by is not None:
        q = q.where(KnowledgeItem.created_by.in_(created_by))
    if created_from is not None:
        q = q.where(KnowledgeItem.created_at >= created_from)
    if created_to is not None:
        q = q.where(KnowledgeItem.created_at < created_to)
    return list(
        db.scalars(
            q.order_by(KnowledgeItem.occurred_on.desc(), KnowledgeItem.created_at.desc()).limit(
                limit
            )
        )
    )


def family_filter(user_ids: list[str]):
    """family_user_ids(JSON 배열) 에 user_ids 중 하나라도 들어 있는 기록 조건. 비면 어느 기록도 맞지 않는다.

    JSON 칸을 문자열로 바꿔 `"<id>"` 가 들어 있는지 본다(SQLite·PostgreSQL 공통; id 는 따옴표로 감싸여 있어서 다른 id 의
    일부와 헷갈리지 않는다)."""
    as_text = cast(KnowledgeItem.family_user_ids, String)
    safe = [u for u in user_ids if u.replace("-", "").replace("_", "").isalnum()]
    return or_(false(), *[as_text.like(f'%"{u}"%', escape="\\") for u in safe])


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
    family_user_ids: list[str] | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    created_by: list[str] | None = None,
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
    if family_user_ids is not None:
        q = q.where(family_filter(family_user_ids))
    if created_from is not None:
        q = q.where(KnowledgeItem.created_at >= created_from)  # 올린 날(UTC 경계, 시작 이상)
    if created_to is not None:
        q = q.where(KnowledgeItem.created_at < created_to)  # (끝 미만)
    if created_by is not None:
        q = q.where(KnowledgeItem.created_by.in_(created_by))  # 올린 사람

    if db.get_bind().dialect.name == "postgresql":
        literal_vec = "[" + ",".join(f"{x:.6f}" for x in query_vec) + "]"
        distance = KnowledgeChunk.embedding.op("<=>", return_type=Float)(
            cast(literal(literal_vec, String), Vector(EMBED_DIM))
        )
        rows = db.execute(q.add_columns(distance.label("distance")).order_by(distance).limit(limit))
        return [(c, i, 1.0 - float(d)) for c, i, d in rows.all()]
    scored = [(c, i, cosine(query_vec, c.embedding)) for c, i in db.execute(q).all()]
    return sorted(scored, key=lambda row: row[2], reverse=True)[:limit]


def _stale_where(embedding_model: str, group_id: str | None) -> list[ColumnElement[bool]]:
    conds = [KnowledgeChunk.embedding_model != embedding_model]
    if group_id:
        conds.append(KnowledgeChunk.group_id == group_id)
    return conds


def stale_chunks(
    db: Session,
    embedding_model: str,
    group_id: str | None = None,
    *,
    after_id: int = 0,
    limit: int | None = None,
) -> list[KnowledgeChunk]:
    """지금 모델이 아닌 모델로 만든 조각을 id 순으로. `after_id` 보다 큰 id 에서 `limit` 개까지(키셋 페이지)."""
    q = select(KnowledgeChunk).where(*_stale_where(embedding_model, group_id))
    if after_id:
        q = q.where(KnowledgeChunk.id > after_id)
    q = q.order_by(KnowledgeChunk.id)
    if limit is not None:
        q = q.limit(limit)
    return list(db.scalars(q))


def count_stale(db: Session, embedding_model: str, group_id: str | None = None) -> int:
    """지금 모델이 아닌 모델로 만든 조각 수."""
    q = (
        select(func.count())
        .select_from(KnowledgeChunk)
        .where(*_stale_where(embedding_model, group_id))
    )
    return int(db.scalar(q) or 0)


def count_by_model(db: Session, group_id: str | None = None) -> dict[str, int]:
    """임베딩 모델 이름별 조각 수."""
    q = select(KnowledgeChunk.embedding_model, func.count()).group_by(
        KnowledgeChunk.embedding_model
    )
    if group_id:
        q = q.where(KnowledgeChunk.group_id == group_id)
    return {model: int(n) for model, n in db.execute(q).all()}


def count_stale_items(db: Session, embedding_model: str, group_id: str | None = None) -> int:
    """다른 모델 조각이 하나라도 있는 기록 수."""
    q = select(func.count(distinct(KnowledgeChunk.item_id))).where(
        *_stale_where(embedding_model, group_id)
    )
    return int(db.scalar(q) or 0)


def count_items_missing_model(
    db: Session, embedding_model: str, group_id: str | None = None
) -> int:
    """조각은 있는데 지금 모델 조각이 하나도 없어, 의미 검색에서 완전히 빠진 기록 수."""
    current = aliased(KnowledgeChunk)
    has_current = exists().where(
        current.item_id == KnowledgeChunk.item_id, current.embedding_model == embedding_model
    )
    q = select(func.count(distinct(KnowledgeChunk.item_id))).where(~has_current)
    if group_id:
        q = q.where(KnowledgeChunk.group_id == group_id)
    return int(db.scalar(q) or 0)


def update_chunk_embedding(
    db: Session, chunk_id: int, embedding_model: str, vector: list[float]
) -> int:
    """벡터와 모델 이름을 함께 쓴다. 이미 지금 모델이거나 그 사이 지워진 조각은 0행이 바뀐다(commit 은 부른 쪽이 한다)."""
    table = KnowledgeChunk.__table__
    result = db.execute(
        update(table)
        .where(table.c.id == chunk_id, table.c.embedding_model != embedding_model)
        .values(embedding=vector, embedding_model=embedding_model)
    )
    return int(result.rowcount or 0)
