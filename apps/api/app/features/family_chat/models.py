from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class Message(Base):
    """가족 그룹의 단체 대화 메시지. TODO: 대화방 여러 개(원본의 rooms), 읽음 표시, 일정 제안."""

    __tablename__ = "messages"
    # 안 읽은 수·읽음 위치 확인이 (group_id, id) 범위로 조회한다
    __table_args__ = (Index("ix_messages_group_id_id", "group_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ChatReadState(Base):
    """구성원별로 가족 대화를 어디까지 읽었는지(마지막으로 읽은 메시지 id). 행이 없으면 아직 읽은 게 없다(0).
    위치는 앞으로만 간다(단조 증가). 안 읽은 수·'아직 안 읽은 사람 수'는 이 값과 메시지 id 로 계산한다."""

    __tablename__ = "chat_read_states"

    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    last_read_message_id: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
