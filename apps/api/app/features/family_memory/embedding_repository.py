"""이미지 임베딩(`photo_embeddings`) DB 접근(PR4). 파생 데이터라 철회·삭제·제외·가족 끄기 때 지운다. 커밋은 부르는 쪽이 한다. 벡터는 정규화된 float32 바이트뿐이다."""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import PhotoEmbedding


def get(db: Session, attachment_id: str) -> PhotoEmbedding | None:
    return db.get(PhotoEmbedding, attachment_id)


def upsert(
    db: Session,
    group_id: str,
    attachment_id: str,
    user_id: str,
    model_id: str,
    model_version: str,
    dim: int,
    vector: bytes,
    now: datetime,
) -> None:
    """같은 사진의 임베딩은 한 줄이다(다시 만들면 덮어쓴다)."""
    row = db.get(PhotoEmbedding, attachment_id)
    if row is None:
        row = PhotoEmbedding(attachment_id=attachment_id, group_id=group_id, user_id=user_id)
        db.add(row)
    row.group_id, row.user_id = group_id, user_id
    row.model_id, row.model_version, row.dim, row.vector, row.created_at = (
        model_id,
        model_version,
        dim,
        vector,
        now,
    )
    db.flush()


def delete_for_attachment(db: Session, attachment_id: str) -> int:
    return (
        db.execute(
            delete(PhotoEmbedding).where(PhotoEmbedding.attachment_id == attachment_id)
        ).rowcount
        or 0
    )


def delete_for_user(db: Session, group_id: str, user_id: str) -> int:
    return (
        db.execute(
            delete(PhotoEmbedding).where(
                PhotoEmbedding.group_id == group_id, PhotoEmbedding.user_id == user_id
            )
        ).rowcount
        or 0
    )


def delete_for_group(db: Session, group_id: str) -> int:
    return (
        db.execute(delete(PhotoEmbedding).where(PhotoEmbedding.group_id == group_id)).rowcount or 0
    )


def count(db: Session, group_id: str | None = None) -> int:
    stmt = select(func.count()).select_from(PhotoEmbedding)
    if group_id is not None:
        stmt = stmt.where(PhotoEmbedding.group_id == group_id)
    return int(db.scalar(stmt) or 0)


def get_many(db: Session, attachment_ids: list[str], chunk: int = 500) -> dict[str, PhotoEmbedding]:
    """여러 사진의 임베딩 줄을 일괄로 읽는다(사진마다 조회하지 않는다). 없는 사진은 빠진다."""
    out: dict[str, PhotoEmbedding] = {}
    for i in range(0, len(attachment_ids), chunk):
        part = attachment_ids[i : i + chunk]
        rows = db.scalars(select(PhotoEmbedding).where(PhotoEmbedding.attachment_id.in_(part)))
        out.update({row.attachment_id: row for row in rows})
    return out
