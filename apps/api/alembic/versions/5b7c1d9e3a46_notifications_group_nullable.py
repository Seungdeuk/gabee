"""notifications group_id nullable

Revision ID: 5b7c1d9e3a46
Revises: 2110458d9b12
Create Date: 2026-11-04 15:00:00.000000

알림 표 notifications.group_id 의 NOT NULL 을 푼다(제약 완화만, 데이터가 사라지는 변경 없음).
가족과 무관한 개인 알림(고객센터 답변 등)은 group_id 를 비워 두기 위해서다. 기존 행과 구 앱 코드(항상 group_id 를 채움)는
그대로 동작한다(expand).
downgrade 는 NOT NULL 을 되돌리기 위해 group_id 가 빈 개인 알림을 먼저 지운다(그 알림이 사라진다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b7c1d9e3a46"
down_revision: str | Sequence[str] | None = "2110458d9b12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("notifications", "group_id", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    """Downgrade schema. group_id 가 빈 개인 알림은 지운 뒤 NOT NULL 로 되돌린다."""
    op.execute("DELETE FROM notifications WHERE group_id IS NULL")
    op.alter_column("notifications", "group_id", existing_type=sa.String(length=32), nullable=False)
