"""play draw stock

이게 뭐게 가비 추천이 AI 로 만든 단어별 선 그림 저장소를 새로 만든다(expand: 기존 테이블은 건드리지 않는다).

Revision ID: c4e81a7d3f26
Revises: 9c4e7a2b1d63
Create Date: 2026-11-18 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e81a7d3f26"
down_revision: str | Sequence[str] | None = "9c4e7a2b1d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "play_draw_stock",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("word", sa.String(length=8), nullable=False),
        sa.Column("strokes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_play_draw_stock_word_created_at",
        "play_draw_stock",
        ["word", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_play_draw_stock_word_created_at", table_name="play_draw_stock")
    op.drop_table("play_draw_stock")
