"""체류시간: 사람·날·탭마다 그날 머문 초 합계 한 줄 — docs/requirements/usage-time.md.

원본 기록("몇 시 몇 분에 무엇을 봤다")은 저장하지 않고 하루 합계만 둔다."""

from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

TABS = ("chat", "family-chat", "schedule", "care", "my", "other")  # 앱 아래쪽 탭 + 그 밖의 화면
APP_TAB = "app"  # 앱 전체 합계와 실행 횟수를 담는 줄
DAY_SECONDS = 24 * 60 * 60


def _now() -> datetime:
    return datetime.now(UTC)


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    __table_args__ = (
        Index("ix_usage_daily_day", "day"),
    )  # 관리자 화면이 최근 30일을 날짜로 찾는다

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)  # 사용한 날(기기 날짜)
    tab: Mapped[str] = mapped_column(String(16), primary_key=True)  # TABS 중 하나 또는 APP_TAB
    seconds: Mapped[int] = mapped_column(Integer, default=0)  # 그날 그 탭에 머문 초 합계(최대 하루)
    opens: Mapped[int] = mapped_column(Integer, default=0)  # 그날 실행 횟수(APP_TAB 줄에만)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
