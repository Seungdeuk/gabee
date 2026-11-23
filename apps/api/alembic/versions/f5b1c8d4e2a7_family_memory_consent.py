"""family memory consent

Revision ID: f5b1c8d4e2a7
Revises: 9c4e7a2b1d63
Create Date: 2026-11-18 10:00:00.000000

AI 추억 분석의 동의·설정 표 세 개를 새로 만든다(ADR 0020·0021 PR1, expand: 새 표만 추가한다. 기존 표·열·데이터는 바꾸지 않는다).
- `family_memory_settings`: 가족 단위 활성화(`enabled` 기본 false, 행이 없어도 꺼짐).
- `member_memory_consents`: 업로더별 동의 기록 `(group_id, user_id)`. 동의 버전 번호·동의·철회·소급 동의 시각만 둔다(문구 원문 없음). 보관 기간은 미결정이라 지우는 배치가 없다.
- `photo_analysis_exclusions`: 업로더가 자기 사진을 AI 분석에서 뺀 기록(`attachment_id` 기본키).
사진 내용·라벨·임베딩을 담는 열은 없다. 가족·사용자·첨부가 지워지면 따라 지운다(ON DELETE CASCADE, `updated_by` 만 SET NULL).
DB CHECK 는 두지 않는다(값 검사는 코드).

배포 순서: **이 마이그레이션을 코드보다 먼저 적용한 뒤 코드를 배포한다**(9c4e7a2b1d63 이 먼저 적용돼 있어야 한다. 처음에는 a3e92b6d1f48 위에 만들었으나, 같은 부모를 쓰는 9c4e7a2b1d63(admin_alert_log)이 먼저 release/1.3 에 병합돼 멀티 head 가 되어 down_revision 만 옮겼다 — DDL 은 같다). 표가 없는 DB 에 새 코드가 먼저 뜨면
스키마 점검(shared/schema.py)이 family_memory 기능만 503(schema_not_ready)으로 막고, 가족 나가기·채팅 사진 삭제의 정리 훅은 표가 없으면 건너뛴다(다른 기능은 영향 없다).
코드 롤백은 이 표들을 남겨 둬도 무해하다(이전 코드는 쓰지 않는다). downgrade 는 표를 지운다(저장된 동의 기록이 사라진다. 되돌릴 때만 의미가 있다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f5b1c8d4e2a7"
down_revision: str | Sequence[str] | None = "9c4e7a2b1d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "family_memory_settings",
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("updated_by", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("group_id"),
    )
    op.create_table(
        "member_memory_consents",
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("consent_version", sa.Integer(), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retro_consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_table(
        "photo_analysis_exclusions",
        sa.Column("attachment_id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["message_attachments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attachment_id"),
    )
    op.create_index(
        op.f("ix_photo_analysis_exclusions_group_id"),
        "photo_analysis_exclusions",
        ["group_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema (저장된 동의·제외 기록이 사라진다)."""
    op.drop_index(
        op.f("ix_photo_analysis_exclusions_group_id"), table_name="photo_analysis_exclusions"
    )
    op.drop_table("photo_analysis_exclusions")
    op.drop_table("member_memory_consents")
    op.drop_table("family_memory_settings")
