"""play photo rec

찰칵! 탐정단 가비 추천: 사진 문제 보관 표(play_photo_rec)를 새로 만들고, 탐정단 문제(play_photos)에 추천 id 칸(rec_id)을 더한다.
expand 전용(기존 칸·데이터는 건드리지 않는다). 현재 head 가 둘(c4e81a7d3f26 이게 뭐게 그림 저장소, f5b1c8d4e2a7 AI 추억 동의)이라 둘을 이 리비전이 합친다.

Revision ID: a7d3c91e5b84
Revises: c4e81a7d3f26, f5b1c8d4e2a7
Create Date: 2026-11-19 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d3c91e5b84"
down_revision: str | Sequence[str] | None = ("c4e81a7d3f26", "f5b1c8d4e2a7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "play_photo_rec",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=True),
        sa.Column("source", sa.SmallInteger(), nullable=False),
        sa.Column("attachment_id", sa.String(length=32), nullable=True),
        sa.Column("image", sa.LargeBinary(), nullable=True),
        sa.Column("kind", sa.SmallInteger(), nullable=False),
        sa.Column("usable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("question", sa.String(length=20), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("answer", sa.String(length=4), nullable=False),
        sa.Column("box_x", sa.Float(), nullable=False),
        sa.Column("box_y", sa.Float(), nullable=False),
        sa.Column("zoom", sa.SmallInteger(), nullable=False),
        sa.Column("prompt_version", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["message_attachments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attachment_id"),
    )
    op.create_index("ix_play_photo_rec_group_id", "play_photo_rec", ["group_id"], unique=False)
    op.add_column("play_photos", sa.Column("rec_id", sa.String(length=32), nullable=True))
    op.create_index("ix_play_photos_rec_id", "play_photos", ["rec_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_play_photos_rec_id", table_name="play_photos")
    op.drop_column("play_photos", "rec_id")
    op.drop_index("ix_play_photo_rec_group_id", table_name="play_photo_rec")
    op.drop_table("play_photo_rec")
