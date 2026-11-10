"""chat message shares

Revision ID: d7c3b19e5a42
Revises: 30ffd13a359a
Create Date: 2026-11-10 12:00:00.000000

채팅방 공유 카드(message_shares) 새 테이블만 추가한다(expand). 메시지 하나에 카드 하나이고, 카드 내용(payload)은 보낸 시점에
서버가 만든 JSON 이다. 기존 테이블·컬럼은 바꾸지 않고 데이터가 사라지는 변경도 없다.
이 테이블이 없는 DB 에서도 소통의 나머지는 열린다(schema.py SUB_FEATURE_PREFIXES: chat_share 하위 기능).
외래키는 ON DELETE CASCADE 다: 이전 코드로 되돌려도(카드 표를 모르는 purge) 방·가족 삭제가 FK 위반으로 500 이 되지 않는다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7c3b19e5a42"
down_revision: str | Sequence[str] | None = "30ffd13a359a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "message_shares",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("room_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_id"], ["chat_rooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index(op.f("ix_message_shares_group_id"), "message_shares", ["group_id"])
    op.create_index(op.f("ix_message_shares_room_id"), "message_shares", ["room_id"])


def downgrade() -> None:
    """Downgrade schema. 공유 카드 내용이 사라진다(메시지 자체와 고정 문구는 남는다)."""
    op.drop_index(op.f("ix_message_shares_room_id"), table_name="message_shares")
    op.drop_index(op.f("ix_message_shares_group_id"), table_name="message_shares")
    op.drop_table("message_shares")
