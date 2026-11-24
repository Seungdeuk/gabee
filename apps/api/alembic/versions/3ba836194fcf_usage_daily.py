"""usage daily

체류시간 표 usage_daily 와 날짜 인덱스를 추가한다(표·인덱스 추가만, 기존 표는 건드리지 않는다).
사람·날·탭마다 그날 머문 초 합계 한 줄이고, app 줄에 앱 전체 합계와 실행 횟수를 둔다.
downgrade 는 이 표만 지운다(체류시간 기록이 사라진다).

Revision ID: 3ba836194fcf
Revises: eab90289ee51
Create Date: 2026-11-19 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3ba836194fcf"
down_revision: str | Sequence[str] | None = "eab90289ee51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "usage_daily",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("tab", sa.String(length=16), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column("opens", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "day", "tab"),
    )
    op.create_index("ix_usage_daily_day", "usage_daily", ["day"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_usage_daily_day", table_name="usage_daily")
    op.drop_table("usage_daily")
