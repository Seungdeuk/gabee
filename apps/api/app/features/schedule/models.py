import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

from .constants import (
    CHECK_KIND_CHECK,
    CHECK_REPEAT_ALL,
    KIND_APPOINTMENT,
    RECIPIENT_WAITING,
    SUGGESTION_PENDING,
)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(UTC)


class Event(Base):
    """일정. 사람마다 자기 줄(`user_id`)을 갖고, 공유하면 받는 사람의 복사본이 생긴다(`origin_id` 가 원본).

    새 컬럼은 코드를 옮기는 동안 비어 있을 수 있어 nullable 이거나 기본값이 있다.
    제거 예정: starts_at(→ start_date·start_time), note(→ memo), created_by(→ user_id), status.
    삭제는 `deleted_at` 을 채우는 소프트 삭제다. source: manual | chat | photo | request.
    """

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(120))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="confirmed")
    source: Mapped[str] = mapped_column(String(16), default="manual")
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    kind: Mapped[int] = mapped_column(Integer, default=KIND_APPOINTMENT, server_default="1")
    place: Mapped[str] = mapped_column(String(200), default="", server_default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    # start_time 이나 end_time 이 비어 있으면 시간 없음, 종일은 00:00~23:59
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    memo: Mapped[str] = mapped_column(Text, default="", server_default="")
    checked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    origin_id: Mapped[str | None] = mapped_column(
        ForeignKey("events.id"), nullable=True, index=True
    )
    topic_id: Mapped[str | None] = mapped_column(
        ForeignKey("events_topics.id"), nullable=True, index=True
    )
    suggestion_id: Mapped[str | None] = mapped_column(
        ForeignKey("events_suggestions.id"), nullable=True
    )
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("events_requests.id"), nullable=True, index=True
    )
    recip_id: Mapped[str | None] = mapped_column(
        ForeignKey("events_request_recipients.id"), nullable=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventTopic(Base):
    """주제(경조사·병원 같은 일정 분류). 사람마다 자기 주제를 만들고 색을 고른다.
    지우면 `deleted_at` 만 채우고, 그 주제를 붙였던 일정은 `topic_id` 를 비운다."""

    __tablename__ = "events_topics"
    __table_args__ = (Index("ix_events_topics_group_user", "group_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(30))
    color: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventRequest(Base):
    """부탁 본문. 부탁한 사람은 한 명이라 `user_id` 컬럼으로 둔다. 받는 사람은 `events_request_recipients`."""

    __tablename__ = "events_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)  # 부탁한 사람
    title: Mapped[str] = mapped_column(String(120))
    place: Mapped[str] = mapped_column(String(200), default="", server_default="")
    memo: Mapped[str] = mapped_column(Text, default="", server_default="")
    start_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # 받는 사람을 바꾼 마지막 시각


class EventRequestRecipient(Base):
    """받는 사람별 답. 부탁한 사람은 본문(`events_requests.user_id`)에서 읽는다."""

    __tablename__ = "events_request_recipients"
    __table_args__ = (UniqueConstraint("request_id", "user_id", name="uq_events_recipients"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)  # 받는 사람
    request_id: Mapped[str] = mapped_column(ForeignKey("events_requests.id"), index=True)
    status: Mapped[int] = mapped_column(
        Integer, default=RECIPIENT_WAITING, server_default=str(RECIPIENT_WAITING)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventSuggestion(Base):
    """미리 저장해 두는 추천. 사람마다 따로. 시간·메모는 없고 사용자가 등록 화면에서 입력한다."""

    __tablename__ = "events_suggestions"
    __table_args__ = (
        Index("ix_events_suggestions_group_user_status", "group_id", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(120))
    place: Mapped[str] = mapped_column(String(200), default="", server_default="")
    kind: Mapped[int] = mapped_column(Integer, default=KIND_APPOINTMENT, server_default="1")
    start_date: Mapped[date] = mapped_column(Date)
    status: Mapped[int] = mapped_column(
        Integer, default=SUGGESTION_PENDING, server_default=str(SUGGESTION_PENDING)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CheckItem(Base):
    """데일리 체크 내 습관. 사람마다 자기 줄(`user_id`)을 갖는다. 삭제는 `deleted_at` 소프트 삭제다(지난 기록 보존).

    날짜별 기록(done·count·confirmed·confirmed_at·메모)은 `CheckLog` 에 둔다. 이 행에는 습관 정의만 있다.
    """

    __tablename__ = "events_check_items"
    __table_args__ = (Index("ix_events_check_items_user_position", "user_id", "position"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[int] = mapped_column(Integer, default=CHECK_KIND_CHECK, server_default="1")
    goal: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 횟수일 때 하루 목표
    unit: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # 횟수일 때 단위(체크 습관은 비어 있음)
    repeat_days: Mapped[str] = mapped_column(
        String(7), default=CHECK_REPEAT_ALL, server_default=CHECK_REPEAT_ALL
    )  # 월~일 순서 1/0, 월 = 첫 글자
    shared: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    notify: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )  # 이름·종류·목표·단위·요일·공개·알림이 실제로 바뀔 때
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 반복 요일을 마지막으로 바꾼 시각(반복 요일 값이 실제로 달라졌을 때만 갱신). 생성 시 NULL.
    repeat_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CheckLog(Base):
    """데일리 체크 날짜별 기록. 습관 하루에 한 줄이며, 그날 처음 체크·횟수·메모를 남길 때만 만든다(자정에 미리 만들지 않는다).

    kind 1 은 done 을, kind 2 는 count·goal 을 쓴다(다른 쪽은 NULL). 메모만 쓴 줄은 done·count 가 NULL 이다.
    confirmed_at 은 완료 상태가 된 시각이다(취소하면 NULL, 다시 완료하면 새 시각). created_at 은 줄이 처음 생긴 시각이다.
    """

    __tablename__ = "events_check_logs"
    __table_args__ = (
        UniqueConstraint("item_id", "log_date", name="uq_events_check_logs_item_date"),
        Index("ix_events_check_logs_log_date", "log_date"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    item_id: Mapped[str] = mapped_column(ForeignKey("events_check_items.id"))
    log_date: Mapped[date] = mapped_column(Date)  # 기록 대상 날짜(한국 시간)
    done: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # kind 1
    count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # kind 2
    goal: Mapped[int | None] = mapped_column(Integer, nullable=True)  # kind 2, 그날의 목표 스냅샷
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    note: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note_shared: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )  # 이 메모를 가족에게 보일지
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CheckCheer(Base):
    """데일리 체크 응원. 보낸 사람(`from_user_id`)과 받은 사람(`to_user_id`)은 같은 가족 그룹이어야 한다(보낼 때 확인, 그룹 열은 없다).
    받은 사람만 고마워(`thanked_at`)와 닫기(`closed_at`)를 할 수 있다. 닫은 카드도 목록에는 남는다."""

    __tablename__ = "events_check_cheers"
    __table_args__ = (
        Index("ix_events_check_cheers_to_sent", "to_user_id", "sent_at"),
        Index("ix_events_check_cheers_pair_sent", "from_user_id", "to_user_id", "sent_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    from_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    to_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[int] = mapped_column(Integer)  # 1 사랑해요 · 2 최고예요 · 3 잘하셨어요
    message: Mapped[str] = mapped_column(String(100))
    chat_left: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    thanked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CheckSetting(Base):
    """데일리 체크 온보딩 완료 표시. 사용자당 한 줄이고, 행이 없으면 아직 안 한 것이다."""

    __tablename__ = "events_check_settings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
