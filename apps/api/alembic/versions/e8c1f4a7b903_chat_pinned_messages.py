"""chat pinned messages

Revision ID: e8c1f4a7b903
Revises: a3c7e9d15f42
Create Date: 2026-10-26 15:38:32.214898

채팅방 고정 메시지(chat_pinned_messages) 새 테이블만 추가한다(expand). 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8c1f4a7b903"
down_revision: str | Sequence[str] | None = "a3c7e9d15f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_pinned_messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("room_id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("pinned_by", sa.String(length=32), nullable=False),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["pinned_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["room_id"], ["chat_rooms.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "message_id", name="uq_chat_pins_room_message"),
    )
    op.create_index(op.f("ix_chat_pinned_messages_group_id"), "chat_pinned_messages", ["group_id"])
    op.create_index("ix_chat_pins_room_pinned_at", "chat_pinned_messages", ["room_id", "pinned_at"])


def downgrade() -> None:
    """Downgrade schema. 고정 메시지 기록이 모두 사라진다(메시지 자체는 그대로)."""
    op.drop_index("ix_chat_pins_room_pinned_at", table_name="chat_pinned_messages")
    op.drop_index(op.f("ix_chat_pinned_messages_group_id"), table_name="chat_pinned_messages")
    op.drop_table("chat_pinned_messages")
