"""drop events who_ids

Revision ID: 7c3f9a1d5b84
Revises: 1ee3e7d2ff2e
Create Date: 2026-10-29 10:00:00.000000

events.who_ids(관련된 사람 id 목록, "누구")를 지운다(contract). 앱·API·에이전트가 이 값을 더 쓰지 않는다.
이 컬럼을 읽거나 쓰는 코드가 모두 배포된 뒤에 적용한다. downgrade 는 빈 목록으로 컬럼만 되살리며 지운 값은 복구되지 않는다.

destructive-approved: PR #141
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c3f9a1d5b84"
down_revision: str | Sequence[str] | None = "1ee3e7d2ff2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("events", "who_ids")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("events", sa.Column("who_ids", sa.JSON(), server_default="[]", nullable=False))
