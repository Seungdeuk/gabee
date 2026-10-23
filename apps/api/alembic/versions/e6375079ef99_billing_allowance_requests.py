"""billing allowance requests

Revision ID: e6375079ef99
Revises: 9eb94b284ac7
Create Date: 2026-10-24 09:00:00.000000

자녀의 용돈 요청(allowance_requests): 요청 -> 부모 승인(장부에 입금) / 거절 / 자녀 취소. 새 테이블만 추가하며
데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6375079ef99"
down_revision: str | Sequence[str] | None = "9eb94b284ac7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "allowance_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("child_id", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("memo", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(length=32), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_amount", sa.Integer(), nullable=True),
        sa.Column("decision_note", sa.String(length=120), nullable=False),
        sa.Column("entry_id", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_allowance_requests_group_id"), "allowance_requests", ["group_id"])
    op.create_index(op.f("ix_allowance_requests_child_id"), "allowance_requests", ["child_id"])


def downgrade() -> None:
    """Downgrade schema. 용돈 요청 내역이 함께 사라진다."""
    op.drop_index(op.f("ix_allowance_requests_child_id"), table_name="allowance_requests")
    op.drop_index(op.f("ix_allowance_requests_group_id"), table_name="allowance_requests")
    op.drop_table("allowance_requests")
