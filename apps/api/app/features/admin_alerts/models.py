"""관리자 알림 기록표 `admin_alert_log`. 알림 한 건이 한 줄이다.

key 는 규칙 이름과 구간으로 만든 지문이라 같은 알림은 한 번만 들어간다(다른 서버가 같은 순간 넣으면 한쪽만 성공).
내용은 숫자와 고정 문구뿐이다. 이름·이메일·사용자 id·오류 본문을 담을 칸이 없다.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class AdminAlertLog(Base):
    __tablename__ = "admin_alert_log"
    __table_args__ = (Index("ix_admin_alert_log_created_at", "created_at"),)

    key: Mapped[str] = mapped_column(String(120), primary_key=True)  # 지문: 규칙 이름 + 구간
    rule: Mapped[str] = mapped_column(String(60))  # 규칙 이름
    severity: Mapped[str] = mapped_column(String(8))  # 긴급 | 주의 | 보통
    message: Mapped[str] = mapped_column(String(200))  # 숫자만 든 문구
    menu: Mapped[str] = mapped_column(String(60))  # 확인할 메뉴 이름
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_by: Mapped[str | None] = mapped_column(String(40), nullable=True)  # 고정 표시 "운영자"
