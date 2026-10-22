"""care location sharing

Revision ID: c245f7ecc68d
Revises: c8d051b07162
Create Date: 2026-10-22 17:10:00.000000

돌봄 위치 공유. 개인 위치정보이므로 동의한 사람의 위치만 저장한다.
- users.location_consent_at: 지금 동의 상태의 정본(동의한 시각, 없으면 미동의). 기존 행은 모두 미동의(null)다.
- location_consent_events: 동의·철회 이력(좌표 없음)
- care_locations: 동의한 사람이 보낸 위치. 보관 기간(7일)이 지나면 서비스가 지운다.
데이터가 사라지는 변경은 없다.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c245f7ecc68d"
down_revision: str | Sequence[str] | None = "c8d051b07162"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users", sa.Column("location_consent_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "location_consent_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("consent", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_location_consent_events_user_id"),
        "location_consent_events",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "care_locations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_care_locations_user_id"), "care_locations", ["user_id"], unique=False)
    op.create_index(
        "ix_care_locations_user_recorded",
        "care_locations",
        ["user_id", "recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema. 저장된 위치와 동의 이력이 함께 사라진다."""
    op.drop_index("ix_care_locations_user_recorded", table_name="care_locations")
    op.drop_index(op.f("ix_care_locations_user_id"), table_name="care_locations")
    op.drop_table("care_locations")
    op.drop_index(op.f("ix_location_consent_events_user_id"), table_name="location_consent_events")
    op.drop_table("location_consent_events")
    op.drop_column("users", "location_consent_at")
