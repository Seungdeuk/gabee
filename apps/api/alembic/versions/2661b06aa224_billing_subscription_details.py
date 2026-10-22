"""billing subscription details

Revision ID: 2661b06aa224
Revises: c245f7ecc68d
Create Date: 2026-10-22 18:30:00.000000

구독·통신비 항목 관리: 통신사, 사용자가 입력한 월 금액, 매월 결제일, 소프트 삭제 시각.
전부 nullable 이라 기존 항목은 그대로(금액 없음, 삭제 안 됨)다. 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2661b06aa224"
down_revision: str | Sequence[str] | None = "c245f7ecc68d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("subscription_items", sa.Column("carrier", sa.String(length=8), nullable=True))
    op.add_column("subscription_items", sa.Column("monthly_fee", sa.Integer(), nullable=True))
    op.add_column("subscription_items", sa.Column("billing_day", sa.Integer(), nullable=True))
    op.add_column(
        "subscription_items", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema. 입력한 월 금액·결제일·통신사가 함께 사라진다."""
    op.drop_column("subscription_items", "deleted_at")
    op.drop_column("subscription_items", "billing_day")
    op.drop_column("subscription_items", "monthly_fee")
    op.drop_column("subscription_items", "carrier")
