"""family todos

Revision ID: d7b3a9f1c248
Revises: c9a4d7e2b605
Create Date: 2026-10-27 12:00:00.000000

공동 할 일(family_todos) 새 테이블만 추가한다(expand). 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7b3a9f1c248"
down_revision: str | Sequence[str] | None = "c9a4d7e2b605"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "family_todos",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("assignee_id", sa.String(length=32), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_by", sa.String(length=32), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["done_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_family_todos_group_id"), "family_todos", ["group_id"])


def downgrade() -> None:
    """Downgrade schema. 공동 할 일 기록이 모두 사라진다."""
    op.drop_index(op.f("ix_family_todos_group_id"), table_name="family_todos")
    op.drop_table("family_todos")
