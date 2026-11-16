"""chat photo check events

Revision ID: a3e92b6d1f48
Revises: d7a41c9e5b02
Create Date: 2026-11-14 10:00:00.000000

사진 판별 상태가 사람 손으로 바뀐 이력 표 `chat_photo_check_events` 를 새로 만든다(T05-b0-2a, expand: 새 표 하나뿐이다. 기존 표·열·데이터는 바꾸지 않는다).
한 줄 = 한 번의 변경: 전후 상태(from_status 는 이전 줄이 없던 예전 사진이면 NULL)·이유 코드·시각. 사진 내용·자유 글은 저장하지 않는다.
첨부·가족을 지우면 이력도 함께 지운다(ON DELETE CASCADE). `actor_user_id` 는 nullable FK + ON DELETE SET NULL(D-19): 사용자 행을 지우거나 익명화해도
이력(전후 상태·이유·시각)은 남고 "누가"만 비워진다. 사용자 식별자를 문자열로 따로 보관하지 않는다. 이 저장소에서 `ON DELETE SET NULL` 은 처음이고,
실제 계정 탈퇴 절차(삭제·익명화, D-7)는 DB 담당자 확인 전이라 바꾸지 않았다(어느 쪽이든 이 표는 안전하다).
DB CHECK 는 두지 않는다(상태·이유 값 검사는 코드).

배포 순서: **이 마이그레이션을 코드보다 먼저 적용한 뒤 코드를 배포한다**(d7a41c9e5b02 가 먼저 적용돼 있어야 한다). 표가 없는 DB 에 새 코드가 먼저 뜨면
스키마 점검(shared/schema.py)이 family_chat 기능 전체를 503(schema_not_ready)으로 막는다. 코드 롤백은 이 표를 남겨 둬도 무해하다(이전 코드는 이 표를 쓰지 않는다).
downgrade 는 표를 지운다(저장된 이력이 사라진다. 되돌릴 때만 의미가 있다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3e92b6d1f48"
down_revision: str | Sequence[str] | None = "d7a41c9e5b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_photo_check_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("attachment_id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=32), nullable=True),
        sa.Column("from_status", sa.String(length=12), nullable=True),
        sa.Column("to_status", sa.String(length=12), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["message_attachments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_photo_check_events_attachment_id"),
        "chat_photo_check_events",
        ["attachment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_photo_check_events_group_id"),
        "chat_photo_check_events",
        ["group_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema (저장된 이력이 사라진다)."""
    op.drop_index(op.f("ix_chat_photo_check_events_group_id"), table_name="chat_photo_check_events")
    op.drop_index(
        op.f("ix_chat_photo_check_events_attachment_id"), table_name="chat_photo_check_events"
    )
    op.drop_table("chat_photo_check_events")
