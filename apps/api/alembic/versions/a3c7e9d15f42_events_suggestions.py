"""events suggestions

Revision ID: a3c7e9d15f42
Revises: f2b6d8c04e31
Create Date: 2026-10-26 12:20:00.000000

미리 저장해 두는 추천(events_suggestions) 새 테이블을 추가하고 events.suggestion_id 에 FK 를 건다(expand).
데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c7e9d15f42"
down_revision: str | Sequence[str] | None = "f2b6d8c04e31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "events_suggestions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("place", sa.String(length=200), server_default="", nullable=False),
        sa.Column("kind", sa.Integer(), server_default="1", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_events_suggestions_group_user_status",
        "events_suggestions",
        ["group_id", "user_id", "status"],
    )
    op.create_foreign_key(
        "fk_events_suggestion_id", "events", "events_suggestions", ["suggestion_id"], ["id"]
    )


def downgrade() -> None:
    """Downgrade schema. 저장해 둔 추천이 모두 사라진다."""
    op.drop_constraint("fk_events_suggestion_id", "events", type_="foreignkey")
    op.drop_index("ix_events_suggestions_group_user_status", table_name="events_suggestions")
    op.drop_table("events_suggestions")
