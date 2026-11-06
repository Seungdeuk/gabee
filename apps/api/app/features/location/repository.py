from datetime import datetime

from sqlalchemy import Float, String, cast, delete, func, literal, select
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember, User

from .models import EMBED_DIM, LocationChunk, LocationPoint, LocationSetting, LocationZone


def add_point(db: Session, point: LocationPoint) -> LocationPoint:
    db.add(point)
    db.flush()
    return point


def recent_points(db: Session, user_id: str, since: datetime) -> list[LocationPoint]:
    return list(
        db.scalars(
            select(LocationPoint)
            .where(LocationPoint.user_id == user_id, LocationPoint.recorded_at >= since)
            .order_by(LocationPoint.recorded_at)
        )
    )


def count_points(db: Session, user_id: str, since: datetime) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(LocationPoint)
            .where(LocationPoint.user_id == user_id, LocationPoint.recorded_at >= since)
        )
        or 0
    )


def latest_point(db: Session, user_id: str, since: datetime) -> LocationPoint | None:
    return db.scalar(
        select(LocationPoint)
        .where(LocationPoint.user_id == user_id, LocationPoint.recorded_at >= since)
        .order_by(LocationPoint.recorded_at.desc())
        .limit(1)
    )


def prune_points(db: Session, user_id: str, before: datetime) -> None:
    db.execute(
        delete(LocationPoint).where(
            LocationPoint.user_id == user_id, LocationPoint.recorded_at < before
        )
    )


def delete_user_data(db: Session, user_id: str) -> None:
    """동의를 철회하거나 위치를 지울 때: 저장된 위치·구역·설정을 모두 지운다."""
    for model in (LocationPoint, LocationZone, LocationSetting, LocationChunk):
        db.execute(delete(model).where(model.user_id == user_id))


def get_zone(db: Session, user_id: str) -> LocationZone | None:
    return db.get(LocationZone, user_id)


def get_setting(db: Session, user_id: str) -> LocationSetting | None:
    return db.get(LocationSetting, user_id)


def group_users(db: Session, group_id: str) -> list[tuple[User, str]]:
    """그룹 구성원과 그 가족 안 권한(owner/admin/member)."""
    rows = db.execute(
        select(User, GroupMember.role)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.joined_at)
    )
    return [(u, r) for u, r in rows]


def replace_chunks(db: Session, user_ids: list[str], chunks: list[LocationChunk]) -> None:
    """해당 사용자들의 기존 조각을 지우고 새 조각을 넣는다(같은 입력이면 항상 같은 결과가 되게 통째로 바꾼다)."""
    if user_ids:
        db.execute(delete(LocationChunk).where(LocationChunk.user_id.in_(user_ids)))
    db.add_all(chunks)
    db.flush()


def search_chunks(
    db: Session,
    group_id: str,
    user_ids: list[str],
    embedding_model: str,
    query_vec: list[float],
    limit: int = 10,
    overlaps: tuple[datetime, datetime] | None = None,
    kinds: tuple[str, ...] | None = None,
) -> list[tuple[LocationChunk, float]]:
    """질문 벡터와 가까운 조각을 점수(코사인 유사도, 클수록 가까움) 순으로 돌려준다.

    user_ids 는 질문한 사람이 볼 수 있는 사용자만 담는다(권한 확인은 부르는 쪽 몫이다). 다른 가족이거나 다른 모델로 만든
    벡터는 처음부터 뺀다. overlaps 가 있으면 그 시간 구간과 겹치는 조각만, kinds 가 있으면 그 종류의 조각만 후보로 한다. PostgreSQL 에서는 pgvector 의 `<=>`(코사인 거리)와 HNSW 인덱스를, SQLite 에서는 파이썬 계산을 쓴다."""
    if not user_ids:
        return []
    q = select(LocationChunk).where(
        LocationChunk.group_id == group_id,
        LocationChunk.user_id.in_(user_ids),
        LocationChunk.embedding_model == embedding_model,
    )
    if overlaps:
        q = q.where(LocationChunk.starts_at < overlaps[1], LocationChunk.ends_at > overlaps[0])
    if kinds:
        q = q.where(LocationChunk.kind.in_(kinds))
    if db.get_bind().dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        literal_vec = "[" + ",".join(f"{x:.6f}" for x in query_vec) + "]"
        distance = LocationChunk.embedding.op("<=>", return_type=Float)(
            cast(literal(literal_vec, String), Vector(EMBED_DIM))
        )
        rows = db.execute(q.add_columns(distance.label("distance")).order_by(distance).limit(limit))
        return [(c, 1.0 - float(d)) for c, d in rows.all()]
    from app.features.ai_assistant.knowledge.embedding import cosine

    scored = [(c, cosine(query_vec, c.embedding)) for c in db.scalars(q)]
    return sorted(scored, key=lambda row: row[1], reverse=True)[:limit]
