"""돌봄 서비스: 위치 공유(지금은 보류, CARE_LOCATION_ENABLED 꺼짐).

데일리 체크·추천·식단·돌봄 기록·돌봄 에이전트는 팀 회의 결과로 지갑 탭 개편 때 지웠다(DB 테이블은 그대로 둔다)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.family_group import repository as group_repo
from app.shared.config import settings
from app.shared.errors import ApiError
from app.shared.location_consent import set_location_consent

from . import config
from . import repository as repo
from .models import CareLocation
from .schemas import (
    ConsentOut,
    LocationBatch,
    LocationSaved,
    LocationsLatest,
    MemberLocation,
)

# ---- 위치 공유 ----
# 위치는 개인정보다. 동의한 사람만 보낼 수 있고, 같은 가족 구성원만 볼 수 있으며, 좌표를 로그에 남기지 않고
# 외부 서비스로 보내지 않는다. 동의를 철회하면 저장된 위치를 바로 지운다.


def location_enabled() -> bool:
    return settings.care_location_enabled


def _require_location_enabled() -> None:
    if not location_enabled():
        raise ApiError(403, "location_disabled", "위치 공유는 지금 사용할 수 없어요")


def location_consent(user) -> ConsentOut:
    return ConsentOut(consent=user.location_consent_at is not None, since=user.location_consent_at)


def set_consent(db: Session, user, consent: bool) -> ConsentOut:
    if consent:
        _require_location_enabled()  # 철회(저장된 위치 삭제)는 꺼져 있어도 할 수 있다
    set_location_consent(db, user, consent, source="care")
    if not consent:
        repo.delete_user_locations(db, user.id)
    return location_consent(user)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def save_locations(db: Session, user, batch: LocationBatch) -> LocationSaved:
    """동의한 사람이 기기에서 잰 위치를 보낸다. 너무 오래됐거나 미래 시각인 점은 버린다."""
    _require_location_enabled()
    if user.location_consent_at is None:
        raise ApiError(403, "consent_required", "위치 공유에 동의해야 위치를 보낼 수 있어요")
    now = datetime.now(UTC)
    oldest = now - timedelta(days=config.LOCATION_RETENTION_DAYS)
    newest = now + timedelta(minutes=config.LOCATION_FUTURE_SKEW_MINUTES)
    rows = [
        CareLocation(
            id=uuid.uuid4().hex[:12],
            user_id=user.id,
            lat=p.lat,
            lng=p.lng,
            accuracy_m=p.accuracy_m,
            recorded_at=_aware(p.recorded_at),
            received_at=now,
        )
        for p in batch.points
        if oldest <= _aware(p.recorded_at) <= newest
    ]
    if rows:
        repo.add_locations(db, rows)
    repo.purge_locations_before(db, oldest)  # 보관 기간이 지난 위치는 쓸 때 함께 지운다
    return LocationSaved(saved=len(rows), skipped=len(batch.points) - len(rows))


def latest_locations(db: Session, group_id: str, user) -> LocationsLatest:
    """가족 구성원의 최신 위치. 동의하지 않은 사람은 좌표 없이 sharing=false 로만 나온다."""
    _require_location_enabled()
    now = datetime.now(UTC)
    since = now - timedelta(days=config.LOCATION_RETENTION_DAYS)
    members: list[MemberLocation] = []
    for m in group_repo.members(db, group_id):
        sharing = m.location_consent_at is not None
        row = repo.latest_location(db, m.id, since) if sharing else None
        recorded = _aware(row.recorded_at) if row else None
        members.append(
            MemberLocation(
                user_id=m.id,
                name=m.name,
                is_me=m.id == user.id,
                sharing=sharing,
                lat=row.lat if row else None,
                lng=row.lng if row else None,
                accuracy_m=row.accuracy_m if row else None,
                recorded_at=recorded,
                minutes_ago=max(0, int((now - recorded).total_seconds() // 60))
                if recorded
                else None,
            )
        )
    return LocationsLatest(members=members, retention_days=config.LOCATION_RETENTION_DAYS)
