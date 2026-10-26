"""chat rooms

Revision ID: b6e2c9f4a187
Revises: d4b8f2a6c013
Create Date: 2026-10-26 10:00:00.000000

대화방(chat_rooms: 가족 전체방·1:1), 1:1 참여자(chat_room_members), 방별 읽음 위치(chat_room_reads) 새 테이블과
messages.room_id(비어 있을 수 있음) 컬럼·인덱스를 추가한다(expand). 데이터가 사라지는 변경은 없다.

기존 데이터 이전:
- 가족(groups)마다 가족 전체방 하나를 만든다.
- room_id 가 비어 있는 기존 메시지를 그 가족의 전체방에 연결한다.
- chat_read_states(옛 읽음 위치)를 chat_room_reads 로 복사한다. 옛 테이블은 지우지 않고 남겨 둔다
  (이후 contract 리비전에서 정리).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6e2c9f4a187"
down_revision: str | Sequence[str] | None = "d4b8f2a6c013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_rooms",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("direct_key", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_rooms_group_id"), "chat_rooms", ["group_id"])
    op.create_index(
        "uq_chat_rooms_one_family_per_group",
        "chat_rooms",
        ["group_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'family'"),
        sqlite_where=sa.text("kind = 'family'"),
    )
    op.create_index(
        "uq_chat_rooms_direct_pair", "chat_rooms", ["group_id", "direct_key"], unique=True
    )
    op.create_table(
        "chat_room_members",
        sa.Column("room_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["chat_rooms.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("room_id", "user_id"),
    )
    op.create_table(
        "chat_room_reads",
        sa.Column("room_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("last_read_message_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["chat_rooms.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("room_id", "user_id"),
    )
    op.add_column("messages", sa.Column("room_id", sa.String(length=32), nullable=True))
    op.create_foreign_key(
        "fk_messages_room_id_chat_rooms", "messages", "chat_rooms", ["room_id"], ["id"]
    )
    op.create_index("ix_messages_room_id_id", "messages", ["room_id", "id"])

    # 기존 데이터를 가족 전체방으로 옮긴다.
    bind = op.get_bind()
    now = datetime.now(UTC)
    rooms = sa.table(
        "chat_rooms",
        sa.column("id", sa.String),
        sa.column("group_id", sa.String),
        sa.column("kind", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    group_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM groups"))]
    if group_ids:
        bind.execute(
            sa.insert(rooms),
            [
                {"id": uuid.uuid4().hex[:12], "group_id": gid, "kind": "family", "created_at": now}
                for gid in group_ids
            ],
        )
    bind.execute(
        sa.text(
            "UPDATE messages SET room_id = ("
            "SELECT r.id FROM chat_rooms r WHERE r.group_id = messages.group_id AND r.kind = 'family'"
            ") WHERE room_id IS NULL"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO chat_room_reads (room_id, user_id, last_read_message_id, updated_at) "
            "SELECT r.id, s.user_id, s.last_read_message_id, s.updated_at "
            "FROM chat_read_states s JOIN chat_rooms r ON r.group_id = s.group_id AND r.kind = 'family'"
        )
    )


def downgrade() -> None:
    """Downgrade schema. 1:1 방과 메시지의 방 연결, 이 리비전 이후의 방별 읽음 위치가 사라진다
    (옛 chat_read_states 는 그대로 남아 있어 가족 전체방 읽음은 업그레이드 시점 값으로 돌아간다)."""
    op.drop_index("ix_messages_room_id_id", table_name="messages")
    op.drop_constraint("fk_messages_room_id_chat_rooms", "messages", type_="foreignkey")
    op.drop_column("messages", "room_id")
    op.drop_table("chat_room_reads")
    op.drop_table("chat_room_members")
    op.drop_index("uq_chat_rooms_direct_pair", table_name="chat_rooms")
    op.drop_index("uq_chat_rooms_one_family_per_group", table_name="chat_rooms")
    op.drop_index(op.f("ix_chat_rooms_group_id"), table_name="chat_rooms")
    op.drop_table("chat_rooms")
