"""pin board snapshot and hides

Revision ID: d079d509f651
Revises: 8ba852cd9c10
Create Date: 2026-10-29 15:10:00.000000

게시판(고정 메시지) 개선(expand):
- chat_pinned_messages.text 컬럼을 추가한다. 올릴 때의 본문 사본이라 원본 메시지를 보낸 사람이 지워도 게시판에 남는다.
  이미 올라가 있는 공지는 이 리비전에서 현재 원본 본문으로 채운다(UPDATE 한 번, 데이터가 사라지지 않는다).
  게시판에 보이는 범위(앞 200자 + 잘렸는지 알아볼 1자)만 저장한다.
- chat_pin_hides 테이블을 새로 만든다. 공지를 "나만 숨기기"한 기록이고 기본키가 (pin_id, user_id)다.
  공지 행이 지워지면 함께 지워지도록 외래키에 ON DELETE CASCADE 를 둔다(공지를 내리거나 교체하는 요청과 숨기기가 겹쳐도,
  이 리비전 이전의 옛 코드가 숨김 기록을 모르고 공지만 지워도 외래키 위반이 나지 않는다).
데이터가 사라지는 변경은 없다(downgrade 는 이 컬럼의 값과 이 테이블을 지운다).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d079d509f651"
down_revision: str | Sequence[str] | None = "8ba852cd9c10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("chat_pinned_messages", sa.Column("text", sa.Text(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE chat_pinned_messages SET text = "
            "(SELECT substr(messages.text, 1, 201) FROM messages WHERE messages.id = chat_pinned_messages.message_id) "
            "WHERE text IS NULL"
        )
    )
    op.create_table(
        "chat_pin_hides",
        sa.Column("pin_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pin_id"], ["chat_pinned_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("pin_id", "user_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("chat_pin_hides")
    op.drop_column("chat_pinned_messages", "text")
