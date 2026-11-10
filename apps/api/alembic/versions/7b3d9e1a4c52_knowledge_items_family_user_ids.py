"""knowledge_items family_user_ids

Revision ID: 7b3d9e1a4c52
Revises: 7d2e4a9c1b38, b4e7a1c92d58
Create Date: 2026-11-02 16:52:40.797676

기록(knowledge_items)에 "글에 등장한 가족 구성원 user_id 목록"(JSON 문자열 배열, nullable) 칸 하나를 추가한다(expand).
새로 올리는 문서의 가족 이름은 `[가족:<user_id>]` 자리표시로 저장되고, 이 칸은 그 사본이라 "누가 나오는 기록인가"
필터에 쓴다. 기존 행은 null 그대로 둔다(백필하지 않는다). 데이터가 사라지는 변경은 없다.
release/1.2 에 head 가 둘(7d2e4a9c1b38 알림, b4e7a1c92d58 메시지 첨부)이라, 이 리비전이 둘을 부모로 삼아 하나로 합친다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7b3d9e1a4c52"
down_revision: str | Sequence[str] | None = ("7d2e4a9c1b38", "b4e7a1c92d58")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("knowledge_items", sa.Column("family_user_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("knowledge_items", "family_user_ids")
