"""care meal logs

Revision ID: 8a21dd425a73
Revises: 719215db61ba
Create Date: 2026-10-23 21:00:00.000000

식단 기록: 그날 아침·점심·저녁에 무엇을 드셨는지(care_meal_logs). 새 테이블만 추가하며 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a21dd425a73"
down_revision: str | Sequence[str] | None = "719215db61ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "care_meal_logs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("meal", sa.String(length=10), nullable=False),
        sa.Column("menu", sa.String(length=60), nullable=False),
        sa.Column("note", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("recorded_by", sa.String(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "date", "meal", name="uq_care_meal_log"),
    )
    op.create_index(op.f("ix_care_meal_logs_group_id"), "care_meal_logs", ["group_id"])
    op.create_index(op.f("ix_care_meal_logs_date"), "care_meal_logs", ["date"])


def downgrade() -> None:
    """Downgrade schema. 기록한 식단이 함께 사라진다."""
    op.drop_index(op.f("ix_care_meal_logs_date"), table_name="care_meal_logs")
    op.drop_index(op.f("ix_care_meal_logs_group_id"), table_name="care_meal_logs")
    op.drop_table("care_meal_logs")
