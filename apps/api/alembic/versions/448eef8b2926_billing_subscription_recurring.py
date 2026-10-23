"""billing subscription recurring

Revision ID: 448eef8b2926
Revises: 2661b06aa224
Create Date: 2026-10-22 20:00:00.000000

구독료를 월별 지출로 만들기(3단계).
- subscription_items.payer_id: 구독료 지출의 결제한 사람(없으면 지출을 만들지 않는다). 기존 항목은 null.
- subscription_items.split_among: 나눌 사람(빈 목록이면 가족 전체). 기존 항목은 빈 목록.
- expenses.subscription_id: 구독 항목으로 만든 지출이면 그 항목 id(같은 달 중복 방지). 기존 지출은 null.
데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "448eef8b2926"
down_revision: str | Sequence[str] | None = "2661b06aa224"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("subscription_items", sa.Column("payer_id", sa.String(length=32), nullable=True))
    op.add_column(
        "subscription_items",
        sa.Column("split_among", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column("expenses", sa.Column("subscription_id", sa.String(length=32), nullable=True))
    op.create_index(
        op.f("ix_expenses_subscription_id"), "expenses", ["subscription_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema. 구독 항목의 결제한 사람·나눌 사람과 지출의 구독 항목 연결이 사라진다."""
    op.drop_index(op.f("ix_expenses_subscription_id"), table_name="expenses")
    op.drop_column("expenses", "subscription_id")
    op.drop_column("subscription_items", "split_among")
    op.drop_column("subscription_items", "payer_id")
