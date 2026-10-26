"""events requests and recipients

Revision ID: f2b6d8c04e31
Revises: e1a5c7b93d20
Create Date: 2026-10-26 12:10:00.000000

부탁 본문(events_requests)과 받는 사람별 답(events_request_recipients) 새 테이블을 추가하고,
events.request_id·recip_id 에 FK 를 건다(expand). 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2b6d8c04e31"
down_revision: str | Sequence[str] | None = "e1a5c7b93d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "events_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("place", sa.String(length=200), server_default="", nullable=False),
        sa.Column("memo", sa.Text(), server_default="", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_events_requests_group_id"), "events_requests", ["group_id"])
    op.create_index(op.f("ix_events_requests_user_id"), "events_requests", ["user_id"])
    op.create_table(
        "events_request_recipients",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["events_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "user_id", name="uq_events_recipients"),
    )
    op.create_index(
        op.f("ix_events_request_recipients_group_id"), "events_request_recipients", ["group_id"]
    )
    op.create_index(
        op.f("ix_events_request_recipients_user_id"), "events_request_recipients", ["user_id"]
    )
    op.create_index(
        op.f("ix_events_request_recipients_request_id"),
        "events_request_recipients",
        ["request_id"],
    )
    op.create_foreign_key(
        "fk_events_request_id", "events", "events_requests", ["request_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_events_recip_id", "events", "events_request_recipients", ["recip_id"], ["id"]
    )


def downgrade() -> None:
    """Downgrade schema. 부탁과 받는 사람별 답 기록이 모두 사라진다."""
    op.drop_constraint("fk_events_recip_id", "events", type_="foreignkey")
    op.drop_constraint("fk_events_request_id", "events", type_="foreignkey")
    op.drop_index(
        op.f("ix_events_request_recipients_request_id"), table_name="events_request_recipients"
    )
    op.drop_index(
        op.f("ix_events_request_recipients_user_id"), table_name="events_request_recipients"
    )
    op.drop_index(
        op.f("ix_events_request_recipients_group_id"), table_name="events_request_recipients"
    )
    op.drop_table("events_request_recipients")
    op.drop_index(op.f("ix_events_requests_user_id"), table_name="events_requests")
    op.drop_index(op.f("ix_events_requests_group_id"), table_name="events_requests")
    op.drop_table("events_requests")
