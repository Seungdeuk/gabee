"""attachment taken_at

Revision ID: 4c1f8a62b7d9
Revises: 8b4e2a71c9d3
Create Date: 2026-11-12 18:00:00.000000

채팅 사진의 촬영 시각 칸(message_attachments.taken_at)만 추가한다(expand). 비어 있을 수 있고(NULL = 촬영일을 알 수 없어 보낸 날 기준),
기본값·인덱스·제약이 없다. 기존 행은 그대로 NULL 이며 데이터를 바꾸거나 지우는 변경이 없다(이미 올라간 사진의 촬영일은 복구할 수 없다).
인덱스는 일부러 만들지 않았다: 타임라인 정렬 키가 COALESCE(taken_at, created_at) 이라 단일 칼럼 인덱스가 맞지 않고, 조회 성능은 타임라인 조회 PR 에서 PostgreSQL 로 측정해 판단한다.

배포 순서: **이 마이그레이션을 먼저 적용한 뒤 새 코드를 배포한다.** 칸이 없는 DB 에 새 코드가 먼저 뜨면 스키마 점검(shared/schema.py)이
모델의 모든 칸을 확인하므로 family_chat 기능 전체가 503(schema_not_ready)이 된다(데이터는 안전하고 마이그레이션 적용 뒤 바로 회복된다).
반대로 DB 를 먼저 올리면 이전 코드는 모르는 nullable 칸을 문제로 보지 않아 그대로 동작한다.
downgrade 는 칸을 삭제하므로 저장된 촬영 시각이 사라진다(되돌릴 때만 의미).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c1f8a62b7d9"
down_revision: str | Sequence[str] | None = "8b4e2a71c9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "message_attachments",
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema (저장된 촬영 시각이 사라진다)."""
    op.drop_column("message_attachments", "taken_at")
