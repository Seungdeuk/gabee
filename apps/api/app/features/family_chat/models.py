import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

FAMILY = "family"  # 가족 전체방(가족마다 하나)
DIRECT = "direct"  # 가족 구성원 두 명의 1:1 방


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class ChatRoom(Base):
    """가족 그룹 안의 대화방. 가족 전체방(kind=family)은 가족마다 하나이고 구성원은 가족 구성원 전원이다.
    1:1 방(kind=direct)은 `chat_room_members` 의 두 명만 본다. 같은 두 사람의 1:1 방은 하나만 만든다."""

    __tablename__ = "chat_rooms"
    __table_args__ = (
        Index(
            "uq_chat_rooms_one_family_per_group",
            "group_id",
            unique=True,
            postgresql_where=text("kind = 'family'"),
            sqlite_where=text("kind = 'family'"),
        ),
        # direct_key 는 가족 전체방에서 null 이라 이 제약은 1:1 방에만 걸린다
        Index("uq_chat_rooms_direct_pair", "group_id", "direct_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default=FAMILY)
    direct_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ChatRoomMember(Base):
    """1:1 방의 참여자. 가족 전체방은 가족 구성원 전원이라 행을 두지 않는다."""

    __tablename__ = "chat_room_members"

    room_id: Mapped[str] = mapped_column(ForeignKey("chat_rooms.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)


class Message(Base):
    """대화방의 메시지. `room_id` 가 비어 있는 옛 메시지는 가족 전체방으로 본다(group_id 기준)."""

    __tablename__ = "messages"
    # 안 읽은 수·읽음 위치 확인이 (group_id, id) 범위로 조회한다
    __table_args__ = (
        Index("ix_messages_group_id_id", "group_id", "id"),
        Index("ix_messages_room_id_id", "room_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    room_id: Mapped[str | None] = mapped_column(ForeignKey("chat_rooms.id"), nullable=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ChatReadState(Base):
    """(옛 구조) 가족 전체방의 읽음 위치. 방별 읽음(`chat_room_reads`)으로 옮겨 더 이상 읽고 쓰지 않는다.
    기존 데이터를 보존하려고 테이블은 남겨 둔다(정리는 이후 contract 리비전)."""

    __tablename__ = "chat_read_states"

    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    last_read_message_id: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ChatRoomRead(Base):
    """구성원별로 대화방을 어디까지 읽었는지(마지막으로 읽은 메시지 id). 행이 없으면 아직 읽은 게 없다(0).
    위치는 앞으로만 간다(단조 증가). 안 읽은 수·'아직 안 읽은 사람 수'는 이 값과 메시지 id 로 계산한다."""

    __tablename__ = "chat_room_reads"

    room_id: Mapped[str] = mapped_column(ForeignKey("chat_rooms.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    last_read_message_id: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
