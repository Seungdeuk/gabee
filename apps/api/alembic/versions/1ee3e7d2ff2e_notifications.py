"""notifications

Revision ID: 1ee3e7d2ff2e
Revises: 2b5b752790b9
Create Date: 2026-10-28 17:12:51.663489

알림함 테이블 notifications 를 추가한다(expand, 새 테이블 1개와 인덱스 2개).
기존 테이블·데이터는 건드리지 않는다. downgrade 는 이 테이블만 지우며 기존 데이터 손실은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1ee3e7d2ff2e"
down_revision: str | Sequence[str] | None = "2b5b752790b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.String(length=200), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("actor_user_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_user_created", "notifications", ["user_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_notifications_user_read", "notifications", ["user_id", "read_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_notifications_user_read", table_name="notifications")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
