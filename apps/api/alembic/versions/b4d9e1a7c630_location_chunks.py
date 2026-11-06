"""location chunks

위치 질문 답변용 요약 조각 테이블 추가(location_chunks, pgvector 384차원). 테이블·인덱스 추가만, 삭제·이름·타입 변경 없음.
좌표는 담지 않고 사람이 읽는 요약 문장과 그 벡터만 둔다. 이 리비전은 feature/hojenn-location-beta 에만 있고
release/1.2 에 병합하지 않는다(베타, 운영 배포 안 함).

Revision ID: b4d9e1a7c630
Revises: 8a3f6c2d9b15
Create Date: 2026-11-06 12:40:25.613417

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d9e1a7c630"
down_revision: str | Sequence[str] | None = "8a3f6c2d9b15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "location_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=384), nullable=False),
        sa.Column("embedding_model", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_location_chunks_embedding_hnsw",
        "location_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        op.f("ix_location_chunks_embedding_model"),
        "location_chunks",
        ["embedding_model"],
        unique=False,
    )
    op.create_index(
        op.f("ix_location_chunks_group_id"), "location_chunks", ["group_id"], unique=False
    )
    op.create_index(
        op.f("ix_location_chunks_user_id"), "location_chunks", ["user_id"], unique=False
    )
    op.create_index(
        "ix_location_chunks_user_starts", "location_chunks", ["user_id", "starts_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_location_chunks_user_starts", table_name="location_chunks")
    op.drop_index(op.f("ix_location_chunks_user_id"), table_name="location_chunks")
    op.drop_index(op.f("ix_location_chunks_group_id"), table_name="location_chunks")
    op.drop_index(op.f("ix_location_chunks_embedding_model"), table_name="location_chunks")
    op.drop_index(
        "ix_location_chunks_embedding_hnsw",
        table_name="location_chunks",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("location_chunks")
    # vector 확장은 다른 기능이 쓸 수 있어 지우지 않는다.
