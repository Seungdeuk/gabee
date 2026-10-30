"""request edited at

Revision ID: b7e4c1a95d36
Revises: d079d509f651
Create Date: 2026-10-29 15:10:00.000000

events_requests.edited_at 컬럼을 추가한다(expand). 보낸 사람이 받는 사람을 바꾼 마지막 시각이고, 바꾸지 않은 기존 부탁은 모두 null 이다.
데이터가 사라지는 변경은 없다(downgrade 는 이 컬럼의 값만 지운다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e4c1a95d36"
down_revision: str | Sequence[str] | None = "d079d509f651"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "events_requests", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("events_requests", "edited_at")
