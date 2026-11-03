"""user is_staff

Revision ID: 7f7a6cbbaea3
Revises: f06220eb955a
Create Date: 2026-10-30 17:35:28.337759

users.is_staff 컬럼을 추가한다(expand). 서비스 운영 관리자 표시이고 기존 사용자는 모두 false 다.
가족 안의 owner·admin 역할과는 별개이며, 앱·API 로는 바꿀 수 없고 DB 에서 직접만 켠다.
데이터가 사라지는 변경은 없다(downgrade 는 이 컬럼의 값만 지운다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f7a6cbbaea3"
down_revision: str | Sequence[str] | None = "f06220eb955a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("is_staff", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "is_staff")
