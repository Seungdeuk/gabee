"""billing allowance ledger

Revision ID: 6417c8cf2722
Revises: f972aab92bdb
Create Date: 2026-10-23 11:00:00.000000

용돈을 월 예산 방식에서 앱 안 장부 방식으로 바꾼다: 고정 용돈 주기(allowance_plans)와 입금·사용 장부
(allowance_entries)를 추가한다. 이전 테이블(allowances, allowance_uses)은 데이터가 사라지지 않도록 그대로 두며
제거는 destructive 승인을 받는 후속 PR 에서 한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6417c8cf2722"
down_revision: str | Sequence[str] | None = "f972aab92bdb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "allowance_plans",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("child_id", sa.String(length=32), nullable=False),
        sa.Column("cycle", sa.String(length=8), nullable=False),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("start_date", sa.String(length=10), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "child_id", name="uq_allowance_plan_child"),
    )
    op.create_index(op.f("ix_allowance_plans_group_id"), "allowance_plans", ["group_id"])
    op.create_index(op.f("ix_allowance_plans_child_id"), "allowance_plans", ["child_id"])

    op.create_table(
        "allowance_entries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("child_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("memo", sa.String(length=120), nullable=False),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("plan_due_date", sa.String(length=10), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("child_id", "plan_due_date", name="uq_allowance_entry_due"),
    )
    op.create_index(op.f("ix_allowance_entries_group_id"), "allowance_entries", ["group_id"])
    op.create_index(op.f("ix_allowance_entries_child_id"), "allowance_entries", ["child_id"])


def downgrade() -> None:
    """Downgrade schema. 입력한 용돈 주기와 장부 내역이 함께 사라진다."""
    op.drop_index(op.f("ix_allowance_entries_child_id"), table_name="allowance_entries")
    op.drop_index(op.f("ix_allowance_entries_group_id"), table_name="allowance_entries")
    op.drop_table("allowance_entries")
    op.drop_index(op.f("ix_allowance_plans_child_id"), table_name="allowance_plans")
    op.drop_index(op.f("ix_allowance_plans_group_id"), table_name="allowance_plans")
    op.drop_table("allowance_plans")
