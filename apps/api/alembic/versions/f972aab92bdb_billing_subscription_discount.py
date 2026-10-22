"""billing subscription discount

Revision ID: f972aab92bdb
Revises: 8a3f0c9d21b7
Create Date: 2026-10-22 19:10:00.000000

구독·통신비 항목에 사용자가 청구서를 보고 직접 입력하는 결합 할인 금액을 추가한다.
nullable 이라 기존 항목은 그대로(할인 금액 없음)다. 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f972aab92bdb"
down_revision: str | Sequence[str] | None = "8a3f0c9d21b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("subscription_items", sa.Column("discount_amount", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema. 입력한 결합 할인 금액이 함께 사라진다."""
    op.drop_column("subscription_items", "discount_amount")
