"""events check logs

Revision ID: 11498574b1ed
Revises: 063b754e4c89
Create Date: 2026-11-03 18:00:00.000000

데일리 체크를 날짜별 기록으로 바꾼다.
- expand: 날짜별 기록 테이블 events_check_logs 를 만든다(습관 하루에 한 줄).
- contract: events_check_items 에서 오늘 기록 컬럼(done·count·confirmed·confirmed_at)을 빼고,
  습관 소프트 삭제용 deleted_at 을 더한다. 반복 요일을 마지막으로 바꾼 시각 repeat_updated_at 과
  습관 수정 시각 updated_at 을 더한다(기존 행은 created_at 으로 채운 뒤 NOT NULL 로 바꾼다).

개발용 데이터는 옮기지 않는다(버려도 된다). downgrade 는 기록 테이블을 지우고 빼 두었던 컬럼을 되살리며,
지운 오늘 기록 값은 복구되지 않는다(컬럼은 기본값으로 채워진다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "11498574b1ed"
down_revision: str | Sequence[str] | None = "063b754e4c89"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "events_check_logs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("goal", sa.Integer(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("note", sa.String(length=100), nullable=True),
        sa.Column("note_shared", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["events_check_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "log_date", name="uq_events_check_logs_item_date"),
    )
    op.create_index(
        "ix_events_check_logs_log_date",
        "events_check_logs",
        ["log_date"],
        unique=False,
    )
    op.drop_column("events_check_items", "done")
    op.drop_column("events_check_items", "count")
    op.drop_column("events_check_items", "confirmed")
    op.drop_column("events_check_items", "confirmed_at")
    op.add_column(
        "events_check_items",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "events_check_items",
        sa.Column("repeat_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "events_check_items",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE events_check_items SET updated_at = created_at")
    with op.batch_alter_table("events_check_items") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("events_check_items", "updated_at")
    op.drop_column("events_check_items", "repeat_updated_at")
    op.drop_column("events_check_items", "deleted_at")
    op.add_column(
        "events_check_items",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "events_check_items",
        sa.Column("confirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("events_check_items", sa.Column("count", sa.Integer(), nullable=True))
    op.add_column("events_check_items", sa.Column("done", sa.Boolean(), nullable=True))
    op.drop_index("ix_events_check_logs_log_date", table_name="events_check_logs")
    op.drop_table("events_check_logs")
