import uuid
from datetime import UTC, date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

EMBED_DIM = 384  # PostgreSQL 의 vector(N) 칸 크기. 파인튜닝 e5-small 의 벡터 길이와 같다


def new_id() -> str:
    return uuid.uuid4().hex


class KnowledgeItem(Base):
    """전처리가 넘긴 기록 한 건(마크다운 글). 원본 파일은 서버 PC에 있고 `source_path` 로 가리킨다."""

    __tablename__ = "knowledge_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    created_by: Mapped[str] = mapped_column(String(32))
    kind_label: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body_md: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str | None] = mapped_column(String(500), default=None)
    occurred_on: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    has_unread_parts: Mapped[bool] = mapped_column(Boolean, default=False)
    sensitivity: Mapped[str] = mapped_column(String(16), default="normal")  # normal | sensitive
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    # 글에 `[가족:<user_id>]` 로 등장한 가족 구성원 user_id 목록(JSON 문자열 배열). 없으면 null.
    # 글(title·body_md·조각)에서 뽑은 사본이라 "누가 나오는 기록인가" 필터에 쓴다. 이전 기록은 채우지 않는다.
    family_user_ids: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    # 이 기록을 만든 가족 채팅 첨부(message_attachments.id). 채팅에 올린 문서가 자동 등록될 때만 채운다(다른 경로로 올린 기록은 null).
    # 같은 첨부가 두 번 등록되지 않게 유일하고, 채팅 메시지를 지우면 이 키로 기록을 찾아 함께 지운다.
    source_attachment_id: Mapped[str | None] = mapped_column(
        String(32), default=None, nullable=True, unique=True
    )


class KnowledgeItemRead(Base):
    """구성원별 문서 읽음 기록. 상세를 연 사용자마다 한 행이고, 본인 것만 조회한다. 문서를 지우면 함께 지운다."""

    __tablename__ = "knowledge_item_reads"

    item_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_items.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class KnowledgeChunk(Base):
    """기록을 쪽·슬라이드·길이로 자른 조각. 검색은 조각 단위로 하고 결과는 기록 단위로 묶는다.

    embedding 은 PostgreSQL 에서는 pgvector 의 vector(384), SQLite(테스트·로컬)에서는 JSON 숫자 목록이다.
    PostgreSQL 에는 코사인 거리용 HNSW 인덱스가 붙는다(Alembic 리비전에서 만든다)."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index(
            "ix_knowledge_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    page_label: Mapped[str | None] = mapped_column(String(80), default=None)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(
        JSON().with_variant(Vector(EMBED_DIM), "postgresql")
    )
    embedding_model: Mapped[str] = mapped_column(String(60), index=True)
