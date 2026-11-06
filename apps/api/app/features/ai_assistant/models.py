from datetime import UTC, date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class Photo(Base):
    """앱이 올린 사진. status: received(받음) → (TODO) analyzed(분류·OCR 완료) | needs_review | failed.
    TODO: 분류·OCR·문서 저장·RAG 질의·주간 리포트·위치 기록(원본 capture, agent 참고)."""

    __tablename__ = "photos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    uploaded_by: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(60))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="received")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class DocumentReminder(Base):
    """올린 문서의 날짜에서 뽑은 "챙길 일". 일정 표(events)는 건드리지 않고 급함·알릴 시점·원본 문서 연결을 여기에 둔다.

    status: proposed(일정으로 잡을지 물을 대상) → scheduled(사용자가 허락해 일정을 만듦) → done | dismissed.
    제목은 가린 글에서 뽑은 것이라 가족 이름은 `[가족:id]` 자리표시로 들어 있다."""

    __tablename__ = "document_reminders"
    __table_args__ = (Index("ix_document_reminders_user_status", "user_id", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(
        String(32)
    )  # 챙길 사람(문서에 가족이 한 명 태그돼 있으면 그 사람, 아니면 올린 사람)
    item_id: Mapped[str] = mapped_column(String(32), index=True)  # 원본 기록(knowledge_items.id)
    title: Mapped[str] = mapped_column(String(120))
    due_date: Mapped[date] = mapped_column(Date)
    due_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    urgent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    lead_days: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )  # 급할 때 며칠 전부터(24시간 단위)
    place: Mapped[str] = mapped_column(
        String(200), default="", server_default=""
    )  # 문서에 적힌 장소(일정을 만들 때 넣는다)
    memo: Mapped[str] = mapped_column(
        String(300), default="", server_default=""
    )  # 문서 핵심 내용 한두 문장(일정 메모)
    prep: Mapped[str] = mapped_column(
        String(200), default="", server_default=""
    )  # 준비물·제출 서류(쉼표로 이은 짧은 목록). 있으면 "준비물 챙기셨나요?"로 묻는다
    status: Mapped[str] = mapped_column(String(12), default="proposed")
    event_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 만들어진 일정
    asked_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )  # "일정으로 잡을까요?"를 물은 횟수
    last_asked_on: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )  # 마지막으로 말했거나 답을 받은 날(그날은 같은 일을 다시 묻지 않는다)
    asked_hours: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 급한 일을 알린 가장 이른 "몇 시간 전" 칸
    followup_asked_on: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )  # 지난 일을 "하셨나요?" 물은 날
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ReminderSetting(Base):
    """챙겨주기(문서 날짜 알림)를 사람마다 켜고 끄는 스위치. 줄이 없으면 켜진 것으로 본다."""

    __tablename__ = "reminder_settings"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
