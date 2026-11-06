"""scheduled push log

예약 푸시(일정 30분 전·할 일 아침 9시)를 이미 보냈다는 기록 테이블 1개를 새로 만든다(expand: 기존 테이블은 건드리지 않고, 데이터가 사라지는 변경은 없다).

Revision ID: f3256ed34da7
Revises: 0dd1c204d717
Create Date: 2026-11-06 16:06:50.634055

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3256ed34da7"
down_revision: str | Sequence[str] | None = "0dd1c204d717"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "scheduled_push_log",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        op.f("ix_scheduled_push_log_user_id"), "scheduled_push_log", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_scheduled_push_log_user_id"), table_name="scheduled_push_log")
    op.drop_table("scheduled_push_log")
