import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class MemberWeeklyNews(Base):
    """구성원 한 명의 한 주 가족 뉴스(저장본). `(group_id, user_id, week_start)` 당 한 줄이고, 본인만 읽는다.

    status: ok(문장·근거가 body·sources 에 있다) | pending(만드는 중) | failed(만들지 못함) | empty(재료가 없는 주).
    body 는 `{"title", "items": [{"text", "source_ids"}]}`, sources 는 `[{"id", "kind", "ref", "label", "date"}]` —
    둘 다 서버가 검증한 값만 들어간다(없으면 null). error_code 는 짧은 고정 코드이고 원문·입력을 담지 않는다.
    가족 삭제는 `group_id` 로 자동 포함된다(shared/group_purge.py). 외래키는 ON DELETE CASCADE 라
    계정·가족이 지워질 때 이 줄도 함께 지워진다."""

    __tablename__ = "member_weekly_news"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "user_id", "week_start", name="uq_member_weekly_news_group_user_week"
        ),
        Index("ix_member_weekly_news_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    week_start: Mapped[date] = mapped_column(Date)  # 그 주의 월요일(서비스 시간대)
    status: Mapped[str] = mapped_column(String(12))
    body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
