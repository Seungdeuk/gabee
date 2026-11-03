"""events check tables

Revision ID: 063b754e4c89
Revises: 5d1c0a7b9e42
Create Date: 2026-11-03 15:38:47.832920

데일리 체크 테이블 3개를 새로 만든다(expand): 내 습관(events_check_items), 응원(events_check_cheers),
온보딩 표시(events_check_settings). 기존 테이블은 건드리지 않아 데이터가 사라지는 변경은 없다.
downgrade 는 세 테이블을 지운다(그 안의 습관·응원·설정 기록이 모두 사라진다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "063b754e4c89"
down_revision: str | Sequence[str] | None = "5d1c0a7b9e42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "events_check_items",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.Integer(), server_default="1", nullable=False),
        sa.Column("goal", sa.Integer(), nullable=True),
        sa.Column("unit", sa.String(length=10), nullable=True),
        sa.Column("repeat_days", sa.String(length=7), server_default="1111111", nullable=False),
        sa.Column("shared", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notify", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("done", sa.Boolean(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_events_check_items_user_position",
        "events_check_items",
        ["user_id", "position"],
        unique=False,
    )
    op.create_table(
        "events_check_cheers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("from_user_id", sa.String(length=32), nullable=False),
        sa.Column("to_user_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=100), nullable=False),
        sa.Column("chat_left", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("thanked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_events_check_cheers_to_sent",
        "events_check_cheers",
        ["to_user_id", "sent_at"],
        unique=False,
    )
    op.create_index(
        "ix_events_check_cheers_pair_sent",
        "events_check_cheers",
        ["from_user_id", "to_user_id", "sent_at"],
        unique=False,
    )
    op.create_table(
        "events_check_settings",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("onboarded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    """Downgrade schema. 데일리 체크의 습관·응원·온보딩 기록이 모두 사라진다."""
    op.drop_table("events_check_settings")
    op.drop_index("ix_events_check_cheers_pair_sent", table_name="events_check_cheers")
    op.drop_index("ix_events_check_cheers_to_sent", table_name="events_check_cheers")
    op.drop_table("events_check_cheers")
    op.drop_index("ix_events_check_items_user_position", table_name="events_check_items")
    op.drop_table("events_check_items")
