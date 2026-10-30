"""message deleted at

Revision ID: 44171263393c
Revises: c5e8a2d71f06
Create Date: 2026-10-29 11:31:07.567004

messages.deleted_at 컬럼을 추가한다(expand). 보낸 사람이 메시지를 지운 시각이고, 지우지 않은 기존 메시지는 모두 null 이다.
지우면 본문(text)과 첨부는 서버에서 비우고 행만 남긴다. 데이터가 사라지는 변경은 없다(downgrade 는 이 컬럼의 값만 지운다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "44171263393c"
down_revision: str | Sequence[str] | None = "c5e8a2d71f06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("messages", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("messages", "deleted_at")
