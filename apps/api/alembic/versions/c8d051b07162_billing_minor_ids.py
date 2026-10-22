"""billing minor ids

Revision ID: c8d051b07162
Revises: 6304cb91e46a
Create Date: 2026-10-22 15:43:26.965687

정산 설정에 미성년 자녀 목록을 둔다(자녀 대상 정산은 미성년 자녀가 있을 때 부모님이 부담).
기존 행은 빈 목록으로 채워진다. 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d051b07162"
down_revision: str | Sequence[str] | None = "6304cb91e46a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "billing_settings",
        sa.Column("minor_ids", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("billing_settings", "minor_ids")
