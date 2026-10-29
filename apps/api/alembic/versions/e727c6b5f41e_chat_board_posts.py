"""chat board posts

Revision ID: e727c6b5f41e
Revises: b7e4c1a95d36
Create Date: 2026-10-29 16:10:00.000000

chat_board_posts 테이블을 새로 만든다(expand). 게시판에 올린 공지의 기록으로, 공지를 내리거나 교체해도 남아 지난 공지를 목록으로 볼 수 있다.
같은 방의 같은 메시지는 한 줄(유니크 (room_id, message_id))이고, 본문은 올릴 때의 전체 사본이다.
이미 올라가 있는 공지는 이 리비전에서 기록으로 복사한다(INSERT ... SELECT 한 번): 원본 메시지가 남아 있으면 원본 전체 본문을,
지워졌으면 이미 저장된 사본(없으면 빈 글자)을 쓴다. 데이터가 사라지는 변경은 없다(downgrade 는 이 테이블을 지운다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e727c6b5f41e"
down_revision: str | Sequence[str] | None = "b7e4c1a95d36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_board_posts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("room_id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("posted_by", sa.String(length=32), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["room_id"], ["chat_rooms.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "message_id", name="uq_chat_board_room_message"),
    )
    op.create_index("ix_chat_board_posts_group_id", "chat_board_posts", ["group_id"])
    op.create_index("ix_chat_board_room_posted_at", "chat_board_posts", ["room_id", "posted_at"])
    op.execute(
        sa.text(
            "INSERT INTO chat_board_posts (id, group_id, room_id, message_id, posted_by, posted_at, text) "
            "SELECT p.id, p.group_id, p.room_id, p.message_id, p.pinned_by, p.pinned_at, "
            "CASE WHEN m.deleted_at IS NULL THEN m.text ELSE COALESCE(p.text, '') END "
            "FROM chat_pinned_messages p JOIN messages m ON m.id = p.message_id"
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_chat_board_room_posted_at", table_name="chat_board_posts")
    op.drop_index("ix_chat_board_posts_group_id", table_name="chat_board_posts")
    op.drop_table("chat_board_posts")
