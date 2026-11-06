"""knowledge items source attachment id

가족 채팅에 올린 문서가 가족 공유 문서함(knowledge_items)에 자동 등록될 때, 어느 채팅 첨부(message_attachments.id)에서 만든 기록인지
잇는 칸 1개를 추가한다(expand: nullable 이라 기존 기록은 그대로 null, 데이터가 사라지는 변경은 없다). 같은 첨부가 두 번 등록되지 않게 유일하다.

Revision ID: 0b23fd640cd4
Revises: f3256ed34da7
Create Date: 2026-11-06 17:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0b23fd640cd4"
down_revision: str | Sequence[str] | None = "f3256ed34da7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 모델의 unique=True 가 PostgreSQL 에서 붙이는 기본 이름과 같게 두어 스키마 일치 검사와 다운그레이드가 맞는다
_UNIQUE = "knowledge_items_source_attachment_id_key"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "knowledge_items", sa.Column("source_attachment_id", sa.String(length=32), nullable=True)
    )
    op.create_unique_constraint(_UNIQUE, "knowledge_items", ["source_attachment_id"])


def downgrade() -> None:
    """Downgrade schema. 채팅 첨부와의 연결 정보가 사라진다(문서함 기록 자체는 남는다)."""
    op.drop_constraint(_UNIQUE, "knowledge_items", type_="unique")
    op.drop_column("knowledge_items", "source_attachment_id")
