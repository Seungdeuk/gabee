"""family memory jobs

Revision ID: b7d2e5f1a846
Revises: 639d80e653b4
Create Date: 2026-11-19 12:00:00.000000

AI 추억 분석 작업 큐 표 하나를 새로 만든다(ADR 0021 PR3, expand: 새 표만 추가한다. 기존 표·열·데이터는 바꾸지 않는다).
- `family_memory_jobs`: 사진 한 장·한 종류당 작업 한 줄(UNIQUE `attachment_id`+`kind` 로 중복 등록 방지). 상태·시도 횟수·재시도 시각(`run_after`)·
  임대 만료 시각(`lease_until`)·선점한 워커 이름·실패 예외 **종류 이름**·취소 사유 코드만 둔다. 사진 내용·라벨·경로·임베딩을 담는 열은 없다.
- 선점 조회용 인덱스 `ix_family_memory_jobs_claim`(`status`, `run_after`)과 가족별 차단용 `ix_family_memory_jobs_group_id`.
- 가족·첨부·사용자가 지워지면 따라 지운다(ON DELETE CASCADE). DB CHECK 는 두지 않는다(상태 값 검사는 코드).

배포 순서: **이 마이그레이션을 코드보다 먼저 적용한 뒤 코드를 배포한다**(639d80e653b4 가 먼저 적용돼 있어야 한다). 표가 없는 DB 에 새 코드가 먼저 뜨면 스키마 점검(shared/schema.py)이
family_memory 기능만 503(schema_not_ready)으로 막고 워커는 그 기능이 준비되기 전까지 선점하지 않으며 정리 훅은 건너뛴다(다른 기능은 영향 없다).
운영에서 워커는 기본 꺼짐(`FAMILY_MEMORY_WORKER_ENABLED=false`)이라 이 표가 생겨도 작업은 만들어지거나 돌지 않는다. 코드 롤백은 이 표를 남겨 둬도 무해하다.
downgrade 는 표를 지운다(대기·완료 작업 기록이 사라진다. 분석 결과는 이 표에 없다. 되돌릴 때만 의미가 있다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d2e5f1a846"
down_revision: str | Sequence[str] | None = "639d80e653b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "family_memory_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("attachment_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=40), nullable=True),
        sa.Column("last_error", sa.String(length=40), nullable=True),
        sa.Column("cancel_reason", sa.String(length=24), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attachment_id"], ["message_attachments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attachment_id", "kind", name="uq_family_memory_jobs_attachment_kind"),
    )
    op.create_index("ix_family_memory_jobs_claim", "family_memory_jobs", ["status", "run_after"])
    op.create_index("ix_family_memory_jobs_group_id", "family_memory_jobs", ["group_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_family_memory_jobs_group_id", table_name="family_memory_jobs")
    op.drop_index("ix_family_memory_jobs_claim", table_name="family_memory_jobs")
    op.drop_table("family_memory_jobs")
