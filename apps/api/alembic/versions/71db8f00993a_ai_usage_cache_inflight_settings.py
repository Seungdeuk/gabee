"""ai usage cache inflight settings

AI 호출 비용 관리 공통 테이블 4개(가족 그룹 AI 동의, 요청별 사용 기록, 결과 캐시, 진행 중 호출 표시).
새 테이블만 추가하는 expand 변경이라 구 코드와 호환된다. 대화·문서 원문과 API 키는 어느 테이블에도 저장하지 않는다.
downgrade 는 이 테이블들의 데이터를 지운다.

Revision ID: 71db8f00993a
Revises: e6375079ef99
Create Date: 2026-10-23 19:24:44.305127

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "71db8f00993a"
down_revision: str | Sequence[str] | None = "e6375079ef99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ai_group_settings",
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("enabled_by", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("group_id"),
    )
    op.create_table(
        "ai_inflight",
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("feature", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("group_id", "slot"),
    )
    op.create_table(
        "ai_result_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("feature", sa.String(length=24), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "feature", "cache_key", name="uq_ai_result_cache_key"),
    )
    op.create_index("ix_ai_result_cache_group", "ai_result_cache", ["group_id"], unique=False)
    op.create_table(
        "ai_usage_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("feature", sa.String(length=24), nullable=False),
        sa.Column("api_calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_usage_logs_group_created", "ai_usage_logs", ["group_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_ai_usage_logs_user_created", "ai_usage_logs", ["user_id", "created_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ai_usage_logs_user_created", table_name="ai_usage_logs")
    op.drop_index("ix_ai_usage_logs_group_created", table_name="ai_usage_logs")
    op.drop_table("ai_usage_logs")
    op.drop_index("ix_ai_result_cache_group", table_name="ai_result_cache")
    op.drop_table("ai_result_cache")
    op.drop_table("ai_inflight")
    op.drop_table("ai_group_settings")
