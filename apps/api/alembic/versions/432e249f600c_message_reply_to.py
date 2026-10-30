"""message reply to

Revision ID: 432e249f600c
Revises: 44171263393c
Create Date: 2026-10-29 13:05:00.000000

messages.reply_to_id 컬럼과 같은 테이블을 가리키는 외래키를 추가한다(expand). 답장하는 원본 메시지 id 이고,
기존 메시지는 모두 null(답장 아님)이라 기존 데이터와 충돌하지 않는다. 데이터가 사라지는 변경은 없다
(downgrade 는 이 컬럼의 값만 지운다). 외래키 이름은 PostgreSQL 기본 이름과 같게 둔다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "432e249f600c"
down_revision: str | Sequence[str] | None = "44171263393c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("messages", sa.Column("reply_to_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "messages_reply_to_id_fkey", "messages", "messages", ["reply_to_id"], ["id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("messages_reply_to_id_fkey", "messages", type_="foreignkey")
    op.drop_column("messages", "reply_to_id")
