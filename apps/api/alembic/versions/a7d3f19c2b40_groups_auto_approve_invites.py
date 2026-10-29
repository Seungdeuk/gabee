"""groups auto approve invites

Revision ID: a7d3f19c2b40
Revises: bfb345450bd6
Create Date: 2026-10-28 18:00:00.000000

groups.auto_approve_invites 컬럼을 추가한다(expand). 초대 코드로 들어온 사람을 관리자 승인 없이
바로 구성원으로 넣을지 정하는 값이고, 기존 가족도 켜짐(true)으로 채워진다. 데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d3f19c2b40"
down_revision: str | Sequence[str] | None = "bfb345450bd6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "groups",
        sa.Column("auto_approve_invites", sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema. 가족별 자동 승인 설정이 사라지고 다시 모두 관리자 승인 방식이 된다."""
    op.drop_column("groups", "auto_approve_invites")
