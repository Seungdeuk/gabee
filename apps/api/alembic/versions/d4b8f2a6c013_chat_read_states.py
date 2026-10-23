"""chat read states

Revision ID: d4b8f2a6c013
Revises: a7d3e1c94b52
Create Date: 2026-10-23 23:00:00.000000

채팅 읽음 상태. 새 테이블 chat_read_states(구성원별 마지막으로 읽은 메시지 id)와
messages 의 (group_id, id) 복합 인덱스만 추가하는 expand 변경이라 구 코드와 호환된다.
데이터가 사라지는 변경은 없다(downgrade 는 새로 만든 테이블·인덱스만 지운다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4b8f2a6c013"
down_revision: str | Sequence[str] | None = "a7d3e1c94b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_read_states",
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("last_read_message_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_index("ix_messages_group_id_id", "messages", ["group_id", "id"], unique=False)


def downgrade() -> None:
    """Downgrade schema. 읽음 위치 기록이 사라진다(메시지는 그대로)."""
    op.drop_index("ix_messages_group_id_id", table_name="messages")
    op.drop_table("chat_read_states")
