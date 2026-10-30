"""users tester consent

Revision ID: c5e8a2d71f06
Revises: 7c3f9a1d5b84, a7d3f19c2b40
Create Date: 2026-10-29 10:30:00.000000

users.tester_consent_version·tester_consent_at 컬럼을 추가한다(expand). 테스트 동의서에 동의한 버전과 시각이고,
기존 사용자는 둘 다 null(미동의)이다. 데이터가 사라지는 변경은 없다.
이 리비전은 갈라져 있던 두 head(7c3f9a1d5b84, a7d3f19c2b40)를 하나로 합치는 역할도 한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5e8a2d71f06"
down_revision: str | Sequence[str] | None = ("7c3f9a1d5b84", "a7d3f19c2b40")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("tester_consent_version", sa.String(length=16), nullable=True))
    op.add_column(
        "users", sa.Column("tester_consent_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "tester_consent_at")
    op.drop_column("users", "tester_consent_version")
