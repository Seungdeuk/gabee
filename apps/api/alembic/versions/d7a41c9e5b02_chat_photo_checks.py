"""chat photo checks

Revision ID: d7a41c9e5b02
Revises: 4c1f8a62b7d9
Create Date: 2026-11-13 18:00:00.000000

가족 전체방 사진의 판별 상태 표 `chat_photo_checks` 를 새로 만든다(T05-b0-1, expand: 새 표 하나뿐이다. 기존 표·열·데이터는 바꾸지 않는다).
사진 한 장당 한 줄(PK = attachment_id, 첨부 삭제 시 연쇄 삭제, group_id 는 가족 삭제 시 연쇄 삭제). 업로드가 같은 트랜잭션에서 `pending` 으로 만든다.
status 는 pending|photo|document|unsure|failed, source 는 auto|manual 이며 값 검사는 코드에서 한다(DB CHECK 를 두지 않아 후속 결정 D-16·D-19
로 상태·이력이 바뀌어도 이 표를 다시 고치지 않는다). 사진 내용·글자 수·OCR 글자는 저장하지 않고 실패는 종류 이름(last_error)만 남긴다.
예전 사진에는 줄이 없다 = 타임라인에 나오지 않는다(fail-closed). 기존 사진 재판별은 이 리비전에 포함하지 않는다.

배포 순서: **이 마이그레이션을 먼저 적용한 뒤 코드를 배포한다.** 표가 없는 DB 에 새 코드가 먼저 뜨면 스키마 점검(shared/schema.py)이
family_chat 기능 전체를 503(schema_not_ready)으로 막는다(업로드가 이 표에 줄을 같은 트랜잭션에 쓰므로 표 없이 업로드만 살리지 않는다).
downgrade 는 표를 지운다(저장된 판별 상태가 사라진다. 되돌릴 때만 의미가 있다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a41c9e5b02"
down_revision: str | Sequence[str] | None = "4c1f8a62b7d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_photo_checks",
        sa.Column("attachment_id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="pending", nullable=False),
        sa.Column("source", sa.String(length=8), server_default="auto", nullable=False),
        sa.Column("last_error", sa.String(length=40), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["message_attachments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("attachment_id"),
    )
    op.create_index(
        op.f("ix_chat_photo_checks_group_id"), "chat_photo_checks", ["group_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema (저장된 판별 상태가 사라진다)."""
    op.drop_index(op.f("ix_chat_photo_checks_group_id"), table_name="chat_photo_checks")
    op.drop_table("chat_photo_checks")
