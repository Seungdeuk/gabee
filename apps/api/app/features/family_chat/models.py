import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, text
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


class MessageAttachment(Base):
    """사진 메시지의 첨부. 메시지 하나에 사진 하나. 파일은 DATA_DIR 아래 서버가 정한 이름으로만 저장하고
    여기에는 상대 경로와 크기만 둔다(원본 EXIF·GPS 는 저장 전에 버린다). 사진 메시지의 text 는 빈 문자열이다."""

    __tablename__ = "message_attachments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), unique=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), index=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("chat_rooms.id"), index=True)
    path: Mapped[str] = mapped_column(String(80))
    thumb_path: Mapped[str] = mapped_column(String(80))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class FamilyTodo(Base):
    """가족이 함께 보는 할 일(공동 할 일). 가족 전체가 보고 고칠 수 있다. 날짜·시간이 있는 약속은 일정(schedule)이고,
    날짜가 없거나 '언제까지'만 있는 부탁·할 일이 여기에 온다. 담당자는 한 명(없을 수 있다), 완료는 done_at 으로 표시한다."""

    __tablename__ = "family_todos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(
        String(10), default="manual"
    )  # manual | chat(AI 후보를 확인해 등록)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
