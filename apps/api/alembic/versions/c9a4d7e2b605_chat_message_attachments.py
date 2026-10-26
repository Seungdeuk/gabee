"""chat message attachments

Revision ID: c9a4d7e2b605
Revises: b6e2c9f4a187
Create Date: 2026-10-27 10:00:00.000000

채팅 사진 첨부(message_attachments) 새 테이블만 추가한다(expand). 메시지 하나에 사진 하나이고, 사진 메시지의 text 는
빈 문자열이다. 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9a4d7e2b605"
down_revision: str | Sequence[str] | None = "b6e2c9f4a187"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "message_attachments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("room_id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.String(length=80), nullable=False),
        sa.Column("thumb_path", sa.String(length=80), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["room_id"], ["chat_rooms.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index(op.f("ix_message_attachments_group_id"), "message_attachments", ["group_id"])
    op.create_index(op.f("ix_message_attachments_room_id"), "message_attachments", ["room_id"])


def downgrade() -> None:
    """Downgrade schema. 사진 첨부 기록이 사라진다(저장된 사진 파일은 DATA_DIR 에 남는다)."""
    op.drop_index(op.f("ix_message_attachments_room_id"), table_name="message_attachments")
    op.drop_index(op.f("ix_message_attachments_group_id"), table_name="message_attachments")
    op.drop_table("message_attachments")
