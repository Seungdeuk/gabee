"""knowledge_item_reads

Revision ID: 27c7716f7207
Revises: 063b754e4c89
Create Date: 2026-11-03 19:25:40.730381

문서 구성원별 읽음 기록 테이블 1개를 새로 만든다(expand): knowledge_item_reads(item_id, user_id, read_at).
기존 테이블은 건드리지 않아 데이터가 사라지는 변경은 없다.
downgrade 는 이 테이블을 지운다(그 안의 읽음 기록이 모두 사라진다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "27c7716f7207"
down_revision: str | Sequence[str] | None = "063b754e4c89"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "knowledge_item_reads",
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["knowledge_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("item_id", "user_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("knowledge_item_reads")
