"""email code and signup relation

이메일 인증·비밀번호 재설정의 6자리 코드(code_hash, 틀린 횟수 failed_attempts)와 가입 시 직접 적은 관계(users.role_detail).
컬럼 추가만 있는 expand 변경이라 구 코드와 호환된다(기존 행은 code_hash NULL → 링크만 가능, failed_attempts 0).
downgrade 는 이 컬럼들의 데이터를 지운다.

Revision ID: 52fe05184992
Revises: 719215db61ba
Create Date: 2026-10-23 14:45:25.640573

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "52fe05184992"
down_revision: str | Sequence[str] | None = "719215db61ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "email_verifications", sa.Column("code_hash", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "email_verifications",
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("password_resets", sa.Column("code_hash", sa.String(length=128), nullable=True))
    op.add_column(
        "password_resets",
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("users", sa.Column("role_detail", sa.String(length=40), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "role_detail")
    op.drop_column("password_resets", "failed_attempts")
    op.drop_column("password_resets", "code_hash")
    op.drop_column("email_verifications", "failed_attempts")
    op.drop_column("email_verifications", "code_hash")
