"""events columns

Revision ID: e1a5c7b93d20
Revises: d7b3a9f1c248
Create Date: 2026-10-26 12:00:00.000000

events 에 사람별 일정·공유 복사본용 컬럼을 추가한다(expand). 기존 컬럼과 데이터는 그대로 둔다.
현재 코드가 이 컬럼 없이 insert 하므로 모두 nullable 이거나 기본값이 있다.
suggestion_id·request_id·recip_id 는 값만 담고, 가리키는 테이블이 생기는 다음 리비전에서 FK 를 건다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1a5c7b93d20"
down_revision: str | Sequence[str] | None = "d7b3a9f1c248"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("events", sa.Column("user_id", sa.String(length=32), nullable=True))
    op.add_column("events", sa.Column("kind", sa.Integer(), server_default="1", nullable=False))
    op.add_column("events", sa.Column("who_ids", sa.JSON(), server_default="[]", nullable=False))
    op.add_column(
        "events", sa.Column("place", sa.String(length=200), server_default="", nullable=False)
    )
    op.add_column("events", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("events", sa.Column("start_time", sa.Time(), nullable=True))
    op.add_column("events", sa.Column("end_time", sa.Time(), nullable=True))
    op.add_column("events", sa.Column("memo", sa.Text(), server_default="", nullable=False))
    op.add_column(
        "events", sa.Column("checked", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("events", sa.Column("origin_id", sa.String(length=32), nullable=True))
    op.add_column("events", sa.Column("suggestion_id", sa.String(length=32), nullable=True))
    op.add_column("events", sa.Column("request_id", sa.String(length=32), nullable=True))
    op.add_column("events", sa.Column("recip_id", sa.String(length=32), nullable=True))
    op.add_column("events", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_events_user_id", "events", "users", ["user_id"], ["id"])
    op.create_foreign_key("fk_events_origin_id", "events", "events", ["origin_id"], ["id"])
    op.create_index(op.f("ix_events_user_id"), "events", ["user_id"])
    op.create_index(op.f("ix_events_start_date"), "events", ["start_date"])
    op.create_index(op.f("ix_events_origin_id"), "events", ["origin_id"])
    op.create_index(op.f("ix_events_request_id"), "events", ["request_id"])


def downgrade() -> None:
    """Downgrade schema. 새 컬럼에 담긴 값이 모두 사라진다."""
    op.drop_index(op.f("ix_events_request_id"), table_name="events")
    op.drop_index(op.f("ix_events_origin_id"), table_name="events")
    op.drop_index(op.f("ix_events_start_date"), table_name="events")
    op.drop_index(op.f("ix_events_user_id"), table_name="events")
    op.drop_constraint("fk_events_origin_id", "events", type_="foreignkey")
    op.drop_constraint("fk_events_user_id", "events", type_="foreignkey")
    for column in (
        "deleted_at",
        "edited_at",
        "recip_id",
        "request_id",
        "suggestion_id",
        "origin_id",
        "checked",
        "memo",
        "end_time",
        "start_time",
        "start_date",
        "place",
        "who_ids",
        "kind",
        "user_id",
    ):
        op.drop_column("events", column)
