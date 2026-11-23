"""photo embeddings

Revision ID: c9a3e7b2d514
Revises: b7d2e5f1a846
Create Date: 2026-11-19 15:00:00.000000

AI 추억 이미지 임베딩 표 하나를 새로 만든다(ADR 0021 PR4, expand: 새 표만 추가한다. 기존 표·열·데이터는 바꾸지 않는다).
- `photo_embeddings`: 사진(첨부) 한 장당 한 줄. 정규화된 float32 벡터(`vector` BYTEA)와 `model_id`·`model_version`·`dim` 만 둔다.
  사진 내용·라벨·경로·OCR 글자를 담는 열은 없다. 가족·첨부·사용자가 지워지면 따라 지운다(ON DELETE CASCADE).
  pgvector 인덱스·유사도 검색은 아직 없다(이 값으로 검색하는 기능이 생길 때 별도 리비전으로 추가한다).
- 인덱스 `ix_photo_embeddings_group_id`: 가족 끄기·철회·가족 삭제 때 가족별로 지우기 위한 것.

배포 순서: **이 마이그레이션을 코드보다 먼저 적용한 뒤 코드를 배포한다**(b7d2e5f1a846 이 먼저 적용돼 있어야 한다). 표가 없는 DB 에 새 코드가 먼저 뜨면 스키마 점검이
family_memory 기능만 503 으로 막는다. 운영에서 서버 스위치·워커·인코더는 모두 기본 꺼짐이라 이 표가 생겨도 임베딩은 만들어지지 않는다. 코드 롤백은 표를 남겨 둬도 무해하다.
downgrade 는 표를 지운다(파생 데이터라 원본은 남는다. 되돌릴 때만 의미가 있다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9a3e7b2d514"
down_revision: str | Sequence[str] | None = "b7d2e5f1a846"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "photo_embeddings",
        sa.Column("attachment_id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=40), nullable=False),
        sa.Column("model_version", sa.String(length=40), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["message_attachments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attachment_id"),
    )
    op.create_index("ix_photo_embeddings_group_id", "photo_embeddings", ["group_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_photo_embeddings_group_id", table_name="photo_embeddings")
    op.drop_table("photo_embeddings")
