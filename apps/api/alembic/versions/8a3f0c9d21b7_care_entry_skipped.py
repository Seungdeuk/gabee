"""care entry skipped

Revision ID: 8a3f0c9d21b7
Revises: 448eef8b2926
Create Date: 2026-10-22 21:30:00.000000

데일리 체크의 '건너뛰기'. 일부러 기록하지 않기로 한 항목은 누락으로 세지 않는다.
기존 기록은 모두 건너뛰기가 아니다(false). 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a3f0c9d21b7"
down_revision: str | Sequence[str] | None = "448eef8b2926"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "care_entries",
        sa.Column("skipped", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema. 건너뛰기 표시가 사라지고 해당 항목은 다시 누락으로 계산된다."""
    op.drop_column("care_entries", "skipped")
