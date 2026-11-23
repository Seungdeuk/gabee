"""memory candidates

Revision ID: d1f4a8c6e293
Revises: c9a3e7b2d514
Create Date: 2026-11-19 18:00:00.000000

AI 추억 후보 저장 표 두 개를 새로 만든다(ADR 0021 PR6, expand: 새 표만 추가한다. 기존 표·열·데이터는 바꾸지 않는다).
- `memory_candidates`: 후보 한 줄(가족 ID·결정적 후보 식별자·대표 사진·그룹화 근거(JSON)·점수·알고리즘 버전·비공개 상태·시각). 사진 자체는 복사하지 않는다.
  같은 입력을 다시 저장해도 한 줄이다(PK = 가족+포함 사진으로 정해지는 식별자).
- `memory_candidate_photos`: 후보에 포함된 사진(첨부 id·순서·대표 순위·중복 대상). 첨부가 지워지면 DB 가 이 줄도 지운다(ON DELETE CASCADE).
가족·후보·첨부·사용자가 지워지면 따라 지운다. 대표 사진이 지워지면 `representative_id` 만 NULL 이 된다(SET NULL, 조회 때 다시 고른다). DB CHECK 는 두지 않는다.

배포 순서: **이 마이그레이션을 코드보다 먼저 적용한 뒤 코드를 배포한다**(c9a3e7b2d514 가 먼저 적용돼 있어야 한다). 표가 없는 DB 에 새 코드가 먼저 뜨면 스키마 점검이
family_memory 기능만 503 으로 막는다. 운영에서 서버 스위치·후보 조회 API 는 모두 기본 꺼짐이고 후보를 만드는 자동 경로가 없어 이 표는 비어 있다. 코드 롤백은 표를 남겨 둬도 무해하다.
downgrade 는 표를 지운다(파생 데이터라 원본은 남는다. 되돌릴 때만 의미가 있다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1f4a8c6e293"
down_revision: str | Sequence[str] | None = "c9a3e7b2d514"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "memory_candidates",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("representative_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=10), server_default="private", nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["representative_id"], ["message_attachments.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_candidates_group_id", "memory_candidates", ["group_id"])
    op.create_table(
        "memory_candidate_photos",
        sa.Column("candidate_id", sa.String(length=32), nullable=False),
        sa.Column("attachment_id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("duplicate_of", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["memory_candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attachment_id"], ["message_attachments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("candidate_id", "attachment_id"),
    )
    op.create_index(
        "ix_memory_candidate_photos_attachment_id", "memory_candidate_photos", ["attachment_id"]
    )
    op.create_index("ix_memory_candidate_photos_group_id", "memory_candidate_photos", ["group_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_memory_candidate_photos_group_id", table_name="memory_candidate_photos")
    op.drop_index("ix_memory_candidate_photos_attachment_id", table_name="memory_candidate_photos")
    op.drop_table("memory_candidate_photos")
    op.drop_index("ix_memory_candidates_group_id", table_name="memory_candidates")
    op.drop_table("memory_candidates")
