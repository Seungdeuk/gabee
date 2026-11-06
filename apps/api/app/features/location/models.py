import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

EMBED_DIM = (
    384  # PostgreSQL 의 vector(N) 칸 크기. 문서 지식(knowledge_chunks)과 같은 e5-small 벡터 길이
)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(UTC)


class LocationPoint(Base):
    """동의한 사람이 보낸 위치. 좌표는 로그에 남기지 않고, LOCATION_RETENTION_DAYS 가 지나면 지운다."""

    __tablename__ = "location_points"
    __table_args__ = (Index("ix_location_points_user_recorded", "user_id", "recorded_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 기기에서 잰 시각
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LocationZone(Base):
    """사용자의 평소 활동 구역(중심과 반경). 최근 위치로 서버가 계산한다. 이탈 알림 상태도 여기에 둔다."""

    __tablename__ = "location_zones"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    center_lat: Mapped[float] = mapped_column(Float)
    center_lng: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer)  # 계산에 쓴 위치 수
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # 마지막으로 구역 이탈을 부모에게 알린 시각(쿨다운 기준). 구역 경계를 오가도 알림이 반복되지 않게 지우지 않는다.
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 마지막으로 잰 위치가 구역 밖인지. 밖에 있는 동안은 구역을 다시 계산하지 않는다.
    outside: Mapped[bool] = mapped_column(Boolean, default=False)


class LocationSetting(Base):
    """사용자별 위치 공유 설정. 일시정지(여행 등)가 끝나는 시각과 앱이 꺼져 있어도 모으는지(백그라운드)."""

    __tablename__ = "location_settings"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 앱이 꺼져 있어도 위치를 모으는 것에 따로 동의했는지. 위치 공유 동의와 별개이고 철회하면 함께 지워진다
    background_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    background_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LocationPlace(Base):
    """사용자가 이름을 붙인 자주 가는 곳(집, 학교). 이름 붙인 본인만 만들고 지운다. 위치 공유를 철회하면 함께 지운다."""

    __tablename__ = "location_places"
    __table_args__ = (Index("ix_location_places_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(String(32))
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(20))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float, default=150.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LocationChunk(Base):
    """위치 기록을 사람이 읽는 요약 문장으로 바꾼 검색 조각(좌표 없음). 질문에 답할 때 가까운 조각만 꺼낸다.

    embedding 은 PostgreSQL 에서는 pgvector 의 vector(384), SQLite(테스트·로컬)에서는 JSON 숫자 목록이다.
    동의 철회·위치 삭제·보관 기간 만료 때 위치와 함께 지운다."""

    __tablename__ = "location_chunks"
    __table_args__ = (
        Index("ix_location_chunks_user_starts", "user_id", "starts_at"),
        Index(
            "ix_location_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)  # 이 위치의 주인
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # span | move | day | place
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(
        JSON().with_variant(Vector(EMBED_DIM), "postgresql")
    )
    embedding_model: Mapped[str] = mapped_column(String(60), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
