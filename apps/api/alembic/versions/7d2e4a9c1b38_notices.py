"""notices

Revision ID: 7d2e4a9c1b38
Revises: 7c1b63d81448
Create Date: 2026-11-05 15:00:00.000000

서비스 공지사항(notices) 새 테이블만 추가한다(expand). 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7d2e4a9c1b38"
down_revision: str | Sequence[str] | None = "7c1b63d81448"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notices",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notices_created", "notices", ["created_at"])


def downgrade() -> None:
    """Downgrade schema. 공지사항이 모두 사라진다."""
    op.drop_index("ix_notices_created", table_name="notices")
    op.drop_table("notices")
