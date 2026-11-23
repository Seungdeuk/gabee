"""play photo rec credit

찰칵! 탐정단 흔한 사진 자동 보충(source 4)의 출처를 남기는 칸을 play_photo_rec 에 더한다:
credit_user(작성자), credit_url(원본 페이지), license, search_query(찾은 검색어), external_id(Pixabay id, 중복 방지용 인덱스).
expand 전용(전부 nullable, 기존 행·데이터는 건드리지 않는다). downgrade 는 칸과 인덱스를 지운다.

Revision ID: d4f7a2b8c351
Revises: b8e2f4a6c917
Create Date: 2026-11-19 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f7a2b8c351"
down_revision: str | Sequence[str] | None = "b8e2f4a6c917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("play_photo_rec", sa.Column("credit_user", sa.String(length=80), nullable=True))
    op.add_column("play_photo_rec", sa.Column("credit_url", sa.String(length=300), nullable=True))
    op.add_column("play_photo_rec", sa.Column("license", sa.String(length=40), nullable=True))
    op.add_column("play_photo_rec", sa.Column("search_query", sa.String(length=60), nullable=True))
    op.add_column("play_photo_rec", sa.Column("external_id", sa.String(length=32), nullable=True))
    op.create_index(
        op.f("ix_play_photo_rec_external_id"), "play_photo_rec", ["external_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_play_photo_rec_external_id"), table_name="play_photo_rec")
    op.drop_column("play_photo_rec", "external_id")
    op.drop_column("play_photo_rec", "search_query")
    op.drop_column("play_photo_rec", "license")
    op.drop_column("play_photo_rec", "credit_url")
    op.drop_column("play_photo_rec", "credit_user")
