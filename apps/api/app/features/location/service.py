"""위치 공유(베타) 업무 규칙. 외부 AI 를 쓰지 않는다: 활동 구역은 최근 위치의 통계로 계산한다.

- 동의한 사람의 위치만 받는다. 동의를 철회하면 저장된 위치·구역·설정을 모두 지운다.
- 최근 위치로 평소 활동 구역(중심·반경)을 만들고, 구역 밖에 있으면 부모(관리자)에게 알림을 보낸다.
- 일시정지(여행 등) 중에는 위치를 받지도 판정하지도 않는다.
- 알림 문구에는 좌표·장소를 넣지 않는다(고정 문구)."""

import math
import statistics
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.errors import ApiError, bad_request
from app.shared.location_consent import set_location_consent
from app.shared.notifications import notify

from . import repository as repo
from .models import LocationPoint, LocationSetting, LocationZone
from .schemas import (
    FamilyLocations,
    MemberLocation,
    MyLocationOut,
    PointIn,
    PointSaved,
    ZoneOut,
)

SOURCE = "location"
ZONE_WINDOW_DAYS = 14  # 구역을 계산하는 최근 기간
ZONE_MIN_POINTS = 20  # 이만큼 모여야 구역을 만든다
ZONE_REFRESH_EVERY = 20  # 구역이 있으면 새 위치가 이만큼 쌓일 때마다 다시 계산
ZONE_MIN_RADIUS_M = 300.0
ZONE_PAD = 1.2  # 90% 위치까지의 거리에 곱하는 여유
ACCURACY_CAP_M = 100.0  # 위치 오차로 구역 판정을 늦추는 상한
ALERT_COOLDOWN = timedelta(hours=6)
FRESH_FOR = timedelta(hours=24)  # 이보다 오래된 마지막 위치는 가족 화면에 쓰지 않는다
NOTIFY_KIND = "care"


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 사이의 거리(m, 하버사인)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def ensure_enabled() -> None:
    if not settings.location_enabled:
        raise ApiError(503, "location_disabled", "위치 공유는 아직 쓸 수 없어요")


def _has_consent(user: User) -> bool:
    return user.location_consent_at is not None


def _is_paused(setting: LocationSetting | None, now: datetime) -> bool:
    return bool(setting and setting.paused_until and _aware(setting.paused_until) > now)


def _zone_out(zone: LocationZone | None) -> ZoneOut | None:
    if zone is None:
        return None
    return ZoneOut(
        center_lat=zone.center_lat,
        center_lng=zone.center_lng,
        radius_m=zone.radius_m,
        sample_count=zone.sample_count,
        computed_at=zone.computed_at,
    )


def _is_outside(zone: LocationZone, lat: float, lng: float, accuracy_m: float | None) -> bool:
    slack = min(accuracy_m or 0.0, ACCURACY_CAP_M)
    return distance_m(lat, lng, zone.center_lat, zone.center_lng) > zone.radius_m + slack


def _parent_ids(db: Session, group_id: str) -> list[str]:
    """알림을 받는 사람: 가입할 때 부모를 고른 사람과 가족 관리자(owner/admin)."""
    return [
        u.id
        for u, group_role in repo.group_users(db, group_id)
        if u.role == "parent" or group_role in ("owner", "admin")
    ]


def compute_zone(points: list[LocationPoint]) -> tuple[float, float, float]:
    """중앙값 중심과 90% 위치까지의 거리로 활동 구역을 정한다(튀는 위치 몇 개에 흔들리지 않는다)."""
    lat = statistics.median(p.lat for p in points)
    lng = statistics.median(p.lng for p in points)
    dists = sorted(distance_m(lat, lng, p.lat, p.lng) for p in points)
    p90 = dists[min(len(dists) - 1, int(len(dists) * 0.9))]
    return lat, lng, max(ZONE_MIN_RADIUS_M, p90 * ZONE_PAD)


def _refresh_zone(db: Session, user: User, group_id: str, now: datetime) -> LocationZone | None:
    since = now - timedelta(days=ZONE_WINDOW_DAYS)
    zone = repo.get_zone(db, user.id)
    total = repo.count_points(db, user.id, since)
    if total < ZONE_MIN_POINTS:
        return zone
    if zone is not None:
        if zone.outside:  # 구역 밖에 있는 동안은 구역을 옮기지 않는다
            return zone
        if total - zone.sample_count < ZONE_REFRESH_EVERY:
            return zone
    lat, lng, radius = compute_zone(repo.recent_points(db, user.id, since))
    if zone is None:
        zone = LocationZone(user_id=user.id, group_id=group_id)
        db.add(zone)
    zone.center_lat, zone.center_lng, zone.radius_m = lat, lng, radius
    zone.sample_count, zone.computed_at = total, now
    return zone


def _alert_parents(db: Session, user: User, group_id: str) -> int:
    return notify(
        db,
        group_id=group_id,
        kind=NOTIFY_KIND,
        event="zone_exit",
        recipients=_parent_ids(db, group_id),
        title="평소와 다른 이동이 감지됐어요",
        body="가족 구성원이 평소 활동 구역을 벗어났어요. 연락해 보세요",
        target_type="location",
        target_id=user.id,
        actor_user_id=user.id,
    )


def _judge(
    db: Session,
    user: User,
    group_id: str,
    zone: LocationZone | None,
    lat: float,
    lng: float,
    accuracy_m: float | None,
    now: datetime,
) -> tuple[bool, bool]:
    """(구역 밖인지, 이번에 부모에게 알렸는지). 알림 사이에는 쿨다운이 있어 경계를 오가도 반복해서 알리지 않는다."""
    if zone is None:
        return False, False
    if not _is_outside(zone, lat, lng, accuracy_m):
        zone.outside = False
        return False, False
    zone.outside = True
    last = zone.alerted_at and _aware(zone.alerted_at)
    if last is not None and now - last < ALERT_COOLDOWN:
        return True, False
    zone.alerted_at = now
    return True, _alert_parents(db, user, group_id) > 0


def my_status(db: Session, user: User) -> MyLocationOut:
    now = _now()
    setting = repo.get_setting(db, user.id)
    paused = _is_paused(setting, now)
    return MyLocationOut(
        enabled=settings.location_enabled,
        consent=_has_consent(user),
        paused_until=setting.paused_until if paused and setting else None,
        paused=paused,
        zone=_zone_out(repo.get_zone(db, user.id)),
        point_count=repo.count_points(db, user.id, now - timedelta(days=ZONE_WINDOW_DAYS)),
    )


def set_consent(db: Session, user: User, consent: bool) -> MyLocationOut:
    if consent:
        ensure_enabled()  # 켜기는 스위치가 꺼져 있으면 막는다. 철회는 항상 열려 있다
    set_location_consent(db, user, consent, SOURCE)
    if not consent:
        repo.delete_user_data(db, user.id)
        db.commit()
    return my_status(db, user)


def delete_my_data(db: Session, user: User) -> MyLocationOut:
    repo.delete_user_data(db, user.id)
    db.commit()
    return my_status(db, user)


def set_pause(db: Session, user: User, group_id: str, days: int | None) -> MyLocationOut:
    ensure_enabled()
    if not _has_consent(user):
        raise bad_request("location_no_consent", "먼저 위치 공유에 동의해 주세요")
    now = _now()
    setting = repo.get_setting(db, user.id) or LocationSetting(user_id=user.id, group_id=group_id)
    was_paused = _is_paused(setting, now)
    setting.group_id = group_id
    setting.paused_until = now + timedelta(days=days) if days else None
    setting.updated_at = now
    db.add(setting)
    if days and not was_paused:  # 일시정지를 켠 사실만 부모에게 알린다(기간·장소는 넣지 않는다)
        notify(
            db,
            group_id=group_id,
            kind=NOTIFY_KIND,
            event="location_paused",
            recipients=_parent_ids(db, group_id),
            title="위치 공유를 잠시 멈췄어요",
            body="가족 구성원이 위치 공유를 일시정지했어요",
            target_type="location",
            target_id=user.id,
            actor_user_id=user.id,
        )
    db.commit()
    return my_status(db, user)


def save_point(db: Session, user: User, group_id: str, body: PointIn) -> PointSaved:
    ensure_enabled()
    if not _has_consent(user):
        return PointSaved(saved=False, reason="no_consent")
    now = _now()
    if _is_paused(repo.get_setting(db, user.id), now):
        return PointSaved(saved=False, reason="paused")
    recorded = _aware(body.recorded_at) if body.recorded_at else now
    if recorded > now + timedelta(minutes=5):
        raise bad_request("invalid_recorded_at", "위치를 잰 시각이 올바르지 않아요")
    repo.add_point(
        db,
        LocationPoint(
            user_id=user.id,
            group_id=group_id,
            lat=body.lat,
            lng=body.lng,
            accuracy_m=body.accuracy_m,
            recorded_at=recorded,
        ),
    )
    repo.prune_points(db, user.id, now - timedelta(days=settings.location_retention_days))
    zone = _refresh_zone(db, user, group_id, now)
    outside, alerted = _judge(db, user, group_id, zone, body.lat, body.lng, body.accuracy_m, now)
    db.commit()
    return PointSaved(saved=True, outside=outside, alerted=alerted)


def simulate_exit(db: Session, user: User, group_id: str, distance: float) -> PointSaved:
    """시연용: 활동 구역 중심에서 북쪽으로 distance(m) 떨어진 곳에 있는 것처럼 판정만 한다. 위치는 저장하지 않는다."""
    ensure_enabled()
    zone = repo.get_zone(db, user.id)
    if not _has_consent(user) or zone is None:
        raise bad_request(
            "location_no_zone", "활동 구역이 아직 없어요. 동의하고 위치가 쌓여야 해요"
        )
    lat = zone.center_lat + math.degrees(distance / 6371000.0)
    outside, alerted = _judge(db, user, group_id, zone, lat, zone.center_lng, None, _now())
    db.commit()
    return PointSaved(saved=False, outside=outside, alerted=alerted)


def family_locations(db: Session, user: User, group_id: str) -> FamilyLocations:
    """부모(관리자)는 동의하고 공유 중인 가족 모두의 마지막 위치를, 그 밖의 사람은 자기 것만 본다."""
    ensure_enabled()
    now = _now()
    can_see = user.id in _parent_ids(db, group_id)
    members: list[MemberLocation] = []
    for member, _ in repo.group_users(db, group_id):
        if member.id != user.id and not can_see:
            continue
        paused = _is_paused(repo.get_setting(db, member.id), now)
        consent = _has_consent(member)
        item = MemberLocation(
            user_id=member.id,
            name=member.name,
            is_me=member.id == user.id,
            sharing=consent and not paused,
            paused=consent and paused,
        )
        if item.sharing:
            point = repo.latest_point(db, member.id, now - FRESH_FOR)
            zone = repo.get_zone(db, member.id)
            if point is not None:
                item.lat, item.lng, item.recorded_at = point.lat, point.lng, point.recorded_at
                item.zone = _zone_out(zone)
                item.outside = bool(
                    zone and _is_outside(zone, point.lat, point.lng, point.accuracy_m)
                )
        members.append(item)
    return FamilyLocations(members=members, can_see_family=can_see)
