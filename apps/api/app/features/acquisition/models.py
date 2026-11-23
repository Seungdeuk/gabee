"""유입 경로: 회원 한 사람이 어떤 홍보 링크로 앱을 설치했는지 한 줄로 남긴다 — docs/requirements/acquisition.md.

플레이 스토어 설치 꼬리표의 utm 세 값만 담는다(꼬리표 원문·광고 클릭 번호는 저장하지 않는다)."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

TAG_MAX = 40  # source·medium·campaign 한 값의 최대 길이


def _now() -> datetime:
    return datetime.now(UTC)


class InstallSource(Base):
    __tablename__ = "install_sources"

    # 한 사람 = 한 줄(기본키). 처음 저장한 경로만 남는다
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(TAG_MAX))  # 어디서 왔나: youtube, google-play …
    medium: Mapped[str | None] = mapped_column(String(TAG_MAX), nullable=True)  # video, organic …
    campaign: Mapped[str | None] = mapped_column(String(TAG_MAX), nullable=True)  # launch …
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
