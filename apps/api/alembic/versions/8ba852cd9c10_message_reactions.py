"""message reactions

Revision ID: 8ba852cd9c10
Revises: 432e249f600c
Create Date: 2026-10-29 14:20:00.000000

message_reactions 테이블을 새로 만든다(expand). 메시지 반응으로, 한 사람이 한 메시지에 하나라 기본키가 (message_id, user_id)다.
기존 테이블·데이터는 바꾸지 않는다. 데이터가 사라지는 변경은 없다(downgrade 는 이 테이블을 지운다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8ba852cd9c10"
down_revision: str | Sequence[str] | None = "432e249f600c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "message_reactions",
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("emoji", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("message_id", "user_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("message_reactions")
