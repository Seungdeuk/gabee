"""member weekly news

Revision ID: 8b4e2a71c9d3
Revises: d7c3b19e5a42
Create Date: 2026-11-10 21:39:34.313773

주간 가족 뉴스 저장 표(member_weekly_news) 새 테이블만 추가한다(expand). 구성원 한 명의 한 주 뉴스가 한 줄이고
`(group_id, user_id, week_start)` 가 유일하다. 기존 테이블·컬럼 변경 없음, 데이터가 사라지는 변경도 없다.
외래키는 ON DELETE CASCADE 다: 이전 코드로 되돌려도(이 표를 모르는 purge) 가족·계정 삭제가 FK 위반으로 500 이 되지 않는다.
downgrade 는 저장된 뉴스를 지운다(뉴스는 다시 만들 수 있는 파생 데이터다).
이 테이블이 없는 DB 에서는 `/report/news` 만 503(`weekly_news` 기능)이고 다른 기능은 열린다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b4e2a71c9d3"
down_revision: str | Sequence[str] | None = "d7c3b19e5a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "member_weekly_news",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("body", sa.JSON(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(length=60), nullable=True),
        sa.Column("prompt_version", sa.String(length=20), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_id", "user_id", "week_start", name="uq_member_weekly_news_group_user_week"
        ),
    )
    op.create_index("ix_member_weekly_news_user_id", "member_weekly_news", ["user_id"])


def downgrade() -> None:
    """Downgrade schema. 저장된 주간 뉴스가 사라진다(다시 만들 수 있는 파생 데이터)."""
    op.drop_index("ix_member_weekly_news_user_id", table_name="member_weekly_news")
    op.drop_table("member_weekly_news")
