"""chat room mutes

Revision ID: c606f5b0deb6
Revises: e727c6b5f41e
Create Date: 2026-10-30 12:32:29.868906

chat_room_mutes 테이블을 새로 만든다(expand). 구성원이 대화방의 알림을 끈 기록으로, 행이 있으면 끈 것이다.
데이터가 사라지는 변경은 없다(downgrade 는 이 테이블을 지운다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c606f5b0deb6"
down_revision: str | Sequence[str] | None = "e727c6b5f41e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_room_mutes",
        sa.Column("room_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["chat_rooms.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("room_id", "user_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("chat_room_mutes")
