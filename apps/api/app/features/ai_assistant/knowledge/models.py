import uuid
from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


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


class KnowledgeChunk(Base):
    """기록을 쪽·슬라이드·길이로 자른 조각. 검색은 조각 단위로 하고 결과는 기록 단위로 묶는다.

    embedding 은 지금은 JSON 숫자 목록이다. PostgreSQL 에서는 pgvector 의 vector(N) 칸으로 옮긴다
    (supabase/migrations 에서 처리, 승인 후)."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    page_label: Mapped[str | None] = mapped_column(String(80), default=None)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(JSON)
    embedding_model: Mapped[str] = mapped_column(String(60), index=True)
