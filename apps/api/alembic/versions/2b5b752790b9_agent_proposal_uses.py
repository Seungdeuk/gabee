"""agent proposal uses

Revision ID: 2b5b752790b9
Revises: bfb345450bd6
Create Date: 2026-10-28 10:19:14.452035

에이전트 쓰기 제안 토큰의 사용 기록 테이블 agent_proposal_uses 를 추가한다(expand, 새 테이블 1개).
기존 테이블·데이터는 건드리지 않고, 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b5b752790b9"
down_revision: str | Sequence[str] | None = "bfb345450bd6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_proposal_uses",
        sa.Column("jti", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("agent_proposal_uses")
