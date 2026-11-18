"""admin alert log

관리자 알림 기록표 admin_alert_log 를 추가한다(표·인덱스 추가만, 기존 표는 건드리지 않는다).
알림 한 건이 한 줄이고, 내용은 숫자와 고정 문구뿐이다(개인 정보 칸 없음).
downgrade 는 이 표만 지운다(알림 기록이 사라진다).

Revision ID: 9c4e7a2b1d63
Revises: a3e92b6d1f48
Create Date: 2026-11-17 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c4e7a2b1d63"
down_revision: str | Sequence[str] | None = "a3e92b6d1f48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "admin_alert_log",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("rule", sa.String(length=60), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("message", sa.String(length=200), nullable=False),
        sa.Column("menu", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acked_by", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        "ix_admin_alert_log_created_at",
        "admin_alert_log",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_admin_alert_log_created_at", table_name="admin_alert_log")
    op.drop_table("admin_alert_log")
