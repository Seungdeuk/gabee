"""위치 공유 동의. 가입(family_group)과 돌봄(care)이 같은 함수로 동의를 바꾸도록 공통 코드로 둔다.

- 지금 동의 상태의 정본은 `users.location_consent_at`(동의한 시각, 없으면 미동의)이다.
- 동의·철회가 있을 때마다 `location_consent_events` 에 이력(언제, 어디서)을 남긴다. 위치 좌표는 담지 않는다.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base


class LocationConsentEvent(Base):
    """동의·철회 이력(감사용). consent=True 가 동의, False 가 철회다."""

    __tablename__ = "location_consent_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    consent: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(16))  # signup | care
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def set_location_consent(db: Session, user, consent: bool, source: str) -> bool:
    """동의 상태를 바꾸고 이력을 남긴다. 이미 같은 상태면 아무것도 하지 않고 False 를 돌려준다.
    `user` 는 `location_consent_at` 속성이 있는 사용자 모델이다."""
    if (user.location_consent_at is not None) == consent:
        return False
    now = datetime.now(UTC)
    user.location_consent_at = now if consent else None
    db.add(user)
    db.add(
        LocationConsentEvent(
            id=uuid.uuid4().hex[:12], user_id=user.id, consent=consent, source=source, at=now
        )
    )
    db.commit()
    return True
