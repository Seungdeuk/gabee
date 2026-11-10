"""message attachment batch id

한 번에 여러 장 올린 사진을 한 묶음으로 보이게 하는 묶음 번호 칸을 추가한다(expand).
nullable 이라 기존 사진은 그대로(묶음 없음, 한 장씩)다. 데이터가 사라지는 변경은 없다.

Revision ID: b4e7a1c92d58
Revises: 5d2a8f1c9b37
Create Date: 2026-11-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4e7a1c92d58"
down_revision: str | Sequence[str] | None = "5d2a8f1c9b37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("message_attachments", sa.Column("batch_id", sa.String(length=32), nullable=True))
    op.create_index(
        op.f("ix_message_attachments_batch_id"), "message_attachments", ["batch_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema. 저장된 묶음 번호가 함께 사라진다(사진은 한 장씩 보인다)."""
    op.drop_index(op.f("ix_message_attachments_batch_id"), table_name="message_attachments")
    op.drop_column("message_attachments", "batch_id")
