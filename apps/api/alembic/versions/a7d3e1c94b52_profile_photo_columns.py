"""profile photo columns

Revision ID: a7d3e1c94b52
Revises: 71db8f00993a
Create Date: 2026-10-23 22:00:00.000000

프로필 사진. users 에 nullable 칼럼 2개(사진 상대 경로, 바꾼 시각)만 추가하는 expand 변경이라 구 코드와 호환된다.
기존 사용자는 모두 NULL(사진 없음). 데이터가 사라지는 변경은 없다(downgrade 는 이 칼럼의 값만 지우며 사진 파일은 DATA_DIR 에 남는다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d3e1c94b52"
down_revision: str | Sequence[str] | None = "71db8f00993a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("profile_photo_path", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("profile_photo_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema. 사진 경로·시각 정보가 사라진다(파일은 남는다)."""
    op.drop_column("users", "profile_photo_updated_at")
    op.drop_column("users", "profile_photo_path")
