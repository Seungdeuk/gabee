"""events topics

Revision ID: bfb345450bd6
Revises: c4d8a2e6b157
Create Date: 2026-10-26 14:00:00.000000

주제(events_topics) 새 테이블을 추가하고, events.topic_id 컬럼과 FK 를 건다(expand).
기존 일정은 topic_id 가 비어 있다. 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bfb345450bd6"
down_revision: str | Sequence[str] | None = "c4d8a2e6b157"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "events_topics",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_topics_group_user", "events_topics", ["group_id", "user_id"])
    op.add_column("events", sa.Column("topic_id", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_events_topic_id"), "events", ["topic_id"])
    op.create_foreign_key("fk_events_topic_id", "events", "events_topics", ["topic_id"], ["id"])


def downgrade() -> None:
    """Downgrade schema. 주제 목록과 일정에 붙인 주제 정보가 모두 사라진다."""
    op.drop_constraint("fk_events_topic_id", "events", type_="foreignkey")
    op.drop_index(op.f("ix_events_topic_id"), table_name="events")
    op.drop_column("events", "topic_id")
    op.drop_index("ix_events_topics_group_user", table_name="events_topics")
    op.drop_table("events_topics")
