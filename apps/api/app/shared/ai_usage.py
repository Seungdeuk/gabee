"""AI 호출 비용 관리용 공통 테이블(여러 FastAPI 워커가 같은 PostgreSQL 로 한도·캐시·동시 실행을 일관되게 다룬다).

- AiGroupSetting: 가족 그룹이 AI 기능 사용에 동의했는지(소유자·관리자가 켠다). 기본은 꺼짐.
- AiUsageLog: 요청별 사용 기록(기능, API 호출 수, 입력·출력 토큰, 캐시 적중, 오류). **대화·문서 원문과 API 키는 저장하지 않는다.**
- AiResultCache: 같은 요청의 결과(가족 그룹별로 격리, 만료 시각까지만 재사용).
- AiInflight: 가족 그룹에서 지금 진행 중인 AI 호출(동시 실행 방지, 죽은 요청은 시간이 지나면 치운다).
"""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class AiGroupSetting(Base):
    __tablename__ = "ai_group_settings"

    group_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AiUsageLog(Base):
    __tablename__ = "ai_usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[str] = mapped_column(String(32))
    feature: Mapped[str] = mapped_column(
        String(24)
    )  # analysis | reply | topics | doc_summary | doc_answer
    api_calls: Mapped[int] = mapped_column(
        Integer, default=0
    )  # 실제로 Anthropic 을 부른 수(캐시 적중은 0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16))  # pending | ok | error | cached
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_ai_usage_logs_group_created", "group_id", "created_at"),
        Index("ix_ai_usage_logs_user_created", "user_id", "created_at"),
    )


class AiResultCache(Base):
    __tablename__ = "ai_result_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(32))
    feature: Mapped[str] = mapped_column(String(24))
    cache_key: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(
        Text
    )  # 검증된 결과 JSON(분석 결과만, 원문 대화는 담지 않는다)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("group_id", "feature", "cache_key", name="uq_ai_result_cache_key"),
        Index("ix_ai_result_cache_group", "group_id"),
    )


class AiInflight(Base):
    __tablename__ = "ai_inflight"

    group_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(
        String(32)
    )  # 이 표시를 만든 요청만 지울 수 있게 한다(오래돼 치워진 뒤 다른 요청의 표시를 지우지 않도록)
    user_id: Mapped[str] = mapped_column(String(32))
    feature: Mapped[str] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
