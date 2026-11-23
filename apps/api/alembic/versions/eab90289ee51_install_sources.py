"""install sources

유입 경로 표 install_sources 를 추가한다(표 추가만, 기존 표는 건드리지 않는다).
회원 한 사람이 한 줄이고, 플레이 스토어 설치 꼬리표의 utm 세 값만 담는다.
downgrade 는 이 표만 지운다(유입 경로 기록이 사라진다).

Revision ID: eab90289ee51
Revises: a3c7e1f5b829
Create Date: 2026-11-18 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eab90289ee51"
down_revision: str | Sequence[str] | None = "a3c7e1f5b829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "install_sources",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("medium", sa.String(length=40), nullable=True),
        sa.Column("campaign", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("install_sources")
