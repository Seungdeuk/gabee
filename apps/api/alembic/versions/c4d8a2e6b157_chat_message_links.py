"""chat message links

Revision ID: c4d8a2e6b157
Revises: e8c1f4a7b903
Create Date: 2026-10-26 16:36:20.463047

채팅 메시지-일정·할 일 연결(chat_message_links) 새 테이블만 추가한다(expand). 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d8a2e6b157"
down_revision: str | Sequence[str] | None = "e8c1f4a7b903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_message_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("room_id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("target_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("time", sa.Time(), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["chat_rooms.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "room_id", "message_id", "kind", "target_id", name="uq_chat_links_room_msg_target"
        ),
    )
    op.create_index(
        "ix_chat_links_room_created_at",
        "chat_message_links",
        ["room_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_message_links_group_id"), "chat_message_links", ["group_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema. 연결 기록이 모두 사라진다(메시지·일정·할 일 자체는 그대로)."""
    op.drop_index(op.f("ix_chat_message_links_group_id"), table_name="chat_message_links")
    op.drop_index("ix_chat_links_room_created_at", table_name="chat_message_links")
    op.drop_table("chat_message_links")
