"""AI 추억 분석의 동의·설정 표(ADR 0020·0021, docs/requirements/auto-memory-consent.md). 이 기능은 기본 꺼짐이다(행이 없으면 꺼짐·미동의).

- `FamilyMemorySetting`: 가족 단위 활성화(소유자·관리자). 기존 대화 분석 동의 `ai_group_settings` 와 **별개**다(읽지도 쓰지도 않는다).
- `MemberMemoryConsent`: 업로더별 동의 기록. 동의 버전·동의 시각·철회 시각·소급 동의 시각만 둔다(문구 원문은 저장하지 않는다).
  보관 기간은 미결정이라 지우는 배치를 만들지 않는다.
- `PhotoAnalysisExclusion`: 업로더가 자기 사진을 AI 분석에서 뺀 기록. 타임라인에서 빼기(`chat_photo_checks.excluded`)와 섞지 않는다.

세 표 모두 `group_id` 열이 있어 가족 삭제(`group_purge`)가 함께 지운다. 사진 내용·라벨은 이 표들에 없다.
(PR3 `FamilyMemoryJob`: 분석 작업 큐. PR4 `PhotoEmbedding`: 분석 결과인 이미지 임베딩 한 벌 — 파생 데이터라 철회·삭제·제외·가족 끄기 때 지운다.)"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
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


class FamilyMemoryJob(Base):
    """AI 추억 분석 작업 큐(PR3, 영속). 서버가 재시작돼도 작업이 남고, 같은 사진·같은 종류는 한 줄뿐이다(중복 방지).
    status: queued(대기) | running(워커가 선점, `lease_until` 까지) | done | failed(시도 상한) | canceled(자격을 잃어 막음).
    `attempts` 는 선점할 때마다 늘고 `max_attempts` 를 넘기면 다시 돌리지 않는다. `run_after` 는 재시도 대기(backoff) 시각이다.
    실패는 예외 **종류 이름**만 `last_error` 에 남기고 사진 내용·라벨·경로·OCR 글자는 어디에도 두지 않는다.
    가족·첨부·사용자가 지워지면 따라 지운다(ON DELETE CASCADE)."""

    __tablename__ = "family_memory_jobs"
    __table_args__ = (
        UniqueConstraint("attachment_id", "kind", name="uq_family_memory_jobs_attachment_kind"),
        Index("ix_family_memory_jobs_claim", "status", "run_after"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("message_attachments.id", ondelete="CASCADE")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))  # 올린 사람
    kind: Mapped[str] = mapped_column(String(24), default="photo_analysis")
    status: Mapped[str] = mapped_column(String(10), default="queued", server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(40), nullable=True)  # 예외 종류 이름만
    cancel_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)  # 사유 코드만
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PhotoAnalysisExclusion(Base):
    __tablename__ = "photo_analysis_exclusions"

    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("message_attachments.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    excluded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PhotoEmbedding(Base):
    """사진 한 장의 이미지 임베딩(PR4, 파생 데이터). 사진 내용·라벨·경로는 없고 정규화된 float32 벡터(`vector`, little-endian)와 모델 정보뿐이다.
    `model_id`·`model_version` 으로 어떤 모델이 만들었는지 구분한다(모델을 바꾸면 이 값이 다른 줄은 쓰지 않는다). 업로더 동의 철회·가족 나가기·
    가족 끄기·사진별 제외·사진 삭제 때 지운다(`memory_hooks`, 같은 트랜잭션). 가족·첨부·사용자가 지워지면 따라 지운다(ON DELETE CASCADE).
    아직 이 값으로 검색·군집화·게시하는 기능은 없다(이후 PR)."""

    __tablename__ = "photo_embeddings"

    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("message_attachments.id", ondelete="CASCADE"), primary_key=True
    )
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))  # 올린 사람
    model_id: Mapped[str] = mapped_column(String(40))
    model_version: Mapped[str] = mapped_column(String(40))
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MemoryCandidate(Base):
    """추억 후보(PR6): PR5 그룹화가 찾은 사진 묶음의 **저장본**. 가족 ID·후보 식별자·대표 사진·그룹화 근거·점수·알고리즘 버전·시각·비공개 상태만 두고 사진 자체는 복사하지 않는다.
    `id` 는 가족+포함 사진으로 정해지는 결정적 값(PR5 `candidate_id`)이라 같은 입력을 다시 저장해도 한 줄이다(멱등). 포함 사진은 `MemoryCandidatePhoto` 에 있다.
    status 는 항상 `private`(자동 게시 없음). 가족·사진이 지워지면 따라 지운다(ON DELETE CASCADE)."""

    __tablename__ = "memory_candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    representative_id: Mapped[str | None] = mapped_column(
        ForeignKey("message_attachments.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(10), default="private", server_default="private")
    score: Mapped[float] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(
        JSON
    )  # 시각 근거(basis·start·end·dated_count·batch_attached_count·bridged)
    algorithm_version: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MemoryCandidatePhoto(Base):
    """추억 후보에 포함된 사진 한 장(첨부 id 와 순서뿐). `rank` 는 대표 후보 순서(0 이 대표, 없으면 NULL), `duplicate_of` 는 중복으로 판정돼 남긴 사진 id 이다.
    `user_id` 는 올린 사람(동의 철회·가족 나가기 때 그 사람의 후보를 지우기 위한 것). 첨부가 지워지면 따라 지운다(ON DELETE CASCADE)."""

    __tablename__ = "memory_candidate_photos"

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("memory_candidates.id", ondelete="CASCADE"), primary_key=True
    )
    attachment_id: Mapped[str] = mapped_column(
        ForeignKey("message_attachments.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duplicate_of: Mapped[str | None] = mapped_column(String(32), nullable=True)
