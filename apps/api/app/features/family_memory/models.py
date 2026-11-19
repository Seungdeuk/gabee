"""AI 추억 분석의 동의·설정 표(ADR 0020·0021, docs/requirements/auto-memory-consent.md). 이 기능은 기본 꺼짐이다(행이 없으면 꺼짐·미동의).

- `FamilyMemorySetting`: 가족 단위 활성화(소유자·관리자). 기존 대화 분석 동의 `ai_group_settings` 와 **별개**다(읽지도 쓰지도 않는다).
- `MemberMemoryConsent`: 업로더별 동의 기록. 동의 버전·동의 시각·철회 시각·소급 동의 시각만 둔다(문구 원문은 저장하지 않는다).
  보관 기간은 미결정이라 지우는 배치를 만들지 않는다.
- `PhotoAnalysisExclusion`: 업로더가 자기 사진을 AI 분석에서 뺀 기록. 타임라인에서 빼기(`chat_photo_checks.excluded`)와 섞지 않는다.

세 표 모두 `group_id` 열이 있어 가족 삭제(`group_purge`)가 함께 지운다. 사진 내용·라벨·임베딩은 이 표들에 없다."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class FamilyMemorySetting(Base):
    __tablename__ = "family_memory_settings"

    group_id: Mapped[str] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MemberMemoryConsent(Base):
    """한 사람의 한 가족에 대한 동의. 지금 유효한 동의 = `consented_at` 있고 `withdrawn_at` 없음.
    소급 분석 동의(`retro_consented_at`)는 새 업로드 분석 동의와 별개이며, 기본 동의가 유효할 때만 유효하다."""

    __tablename__ = "member_memory_consents"

    group_id: Mapped[str] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    consent_version: Mapped[int] = mapped_column(Integer, default=1)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retro_consented_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PhotoAnalysisExclusion(Base):
    __tablename__ = "photo_analysis_exclusions"

    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("message_attachments.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    excluded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
