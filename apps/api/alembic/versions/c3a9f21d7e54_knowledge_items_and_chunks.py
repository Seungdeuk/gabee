"""knowledge items and chunks (pgvector)

Revision ID: c3a9f21d7e54
Revises: 6304cb91e46a
Create Date: 2026-10-22 18:30:00.000000

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a9f21d7e54"
down_revision: str | Sequence[str] | None = "6304cb91e46a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_items",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("kind_label", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("source_path", sa.String(length=500), nullable=True),
        sa.Column("occurred_on", sa.Date(), nullable=True),
        sa.Column("has_unread_parts", sa.Boolean(), nullable=False),
        sa.Column("sensitivity", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_items_group_id"), "knowledge_items", ["group_id"])
    op.create_index(op.f("ix_knowledge_items_kind_label"), "knowledge_items", ["kind_label"])
    op.create_index(op.f("ix_knowledge_items_occurred_on"), "knowledge_items", ["occurred_on"])
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("page_label", sa.String(length=80), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=384), nullable=False),
        sa.Column("embedding_model", sa.String(length=60), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["knowledge_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_chunks_item_id"), "knowledge_chunks", ["item_id"])
    op.create_index(op.f("ix_knowledge_chunks_group_id"), "knowledge_chunks", ["group_id"])
    op.create_index(
        op.f("ix_knowledge_chunks_embedding_model"), "knowledge_chunks", ["embedding_model"]
    )
    op.create_index(
        "ix_knowledge_chunks_embedding_hnsw",
        "knowledge_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_knowledge_chunks_embedding_hnsw", table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_embedding_model"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_group_id"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_item_id"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_items_occurred_on"), table_name="knowledge_items")
    op.drop_index(op.f("ix_knowledge_items_kind_label"), table_name="knowledge_items")
    op.drop_index(op.f("ix_knowledge_items_group_id"), table_name="knowledge_items")
    op.drop_table("knowledge_items")
    # vector 확장은 다른 기능이 쓸 수 있어 지우지 않는다.
