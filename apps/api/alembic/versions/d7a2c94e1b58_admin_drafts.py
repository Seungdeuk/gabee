"""admin drafts

관리자 AI 초안 대기함 표 admin_drafts 와 인덱스를 추가한다(표·인덱스 추가만, 기존 표는 건드리지 않는다).
공지 초안·문의 답변 초안·자동 공지 기록이 한 줄씩 들어간다. 회원 이름·연락처·사용자 id 칸은 없다.
downgrade 는 이 표만 지운다(대기 중인 초안과 자동 공지 기록이 사라진다. 이미 올린 공지는 notices 에 그대로 있다).

Revision ID: d7a2c94e1b58
Revises: 3ba836194fcf
Create Date: 2026-11-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a2c94e1b58"
down_revision: str | Sequence[str] | None = "3ba836194fcf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "admin_drafts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("ticket_id", sa.String(length=32), nullable=True),
        sa.Column("category", sa.String(length=16), nullable=True),
        sa.Column("title", sa.String(length=100), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("auto", sa.Boolean(), nullable=False),
        sa.Column("notice_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "source_key", name="uq_admin_drafts_kind_source"),
    )
    op.create_index(
        "ix_admin_drafts_status_created", "admin_drafts", ["status", "created_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_admin_drafts_status_created", table_name="admin_drafts")
    op.drop_table("admin_drafts")
