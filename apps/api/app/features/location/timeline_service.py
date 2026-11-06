"""이동 기록 타임라인과 장소 이름 붙이기 업무 규칙. 구간은 저장하지 않고 요청 때 저장된 위치 점으로 만든다(파생 데이터를 따로 남기지 않는다).

- 볼 수 있는 사람: 본인, 그리고 부모(가족 owner·admin·부모)는 가족 전체. 응답에 좌표는 없다.
- 장소 이름은 본인만 붙이고 지운다. 자주 간 이름 없는 곳은 좌표 대신 격자 id(candidate_id)로 가리킨다."""

from datetime import UTC, date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.errors import ApiError, bad_request, not_found

from . import repository as repo
from . import service
from . import timeline as tl
from .models import LocationPlace
from .schemas import (
    CandidateOut,
    NamePlaceIn,
    PlaceOut,
    PlacesOut,
    SegmentOut,
    TimelineOut,
)

MAX_PLACES = 20
CANDIDATE_WINDOW_DAYS = 14


def _kst() -> timezone:
    return timezone(timedelta(hours=settings.ai_day_utc_offset_hours))


def _as_utc(value: datetime) -> datetime:
    """DB 에서 읽은 시각(SQLite 는 시간대 없이 UTC 벽시계)을 UTC 시간대가 있는 값으로."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _points(db: Session, user_id: str, start: datetime, end: datetime) -> list[tl.Pt]:
    kst = _kst()
    return [
        tl.Pt(_as_utc(p.recorded_at).astimezone(kst), p.lat, p.lng, p.accuracy_m)
        for p in repo.points_between(db, user_id, start.astimezone(UTC), end.astimezone(UTC))
    ]


def _known(db: Session, user_id: str) -> list[tl.KnownPlace]:
    return [
        tl.KnownPlace(p.id, p.name, p.lat, p.lng, p.radius_m) for p in repo.list_places(db, user_id)
    ]


def _zone_ref(db: Session, user_id: str) -> tl.ZoneRef | None:
    zone = repo.get_zone(db, user_id)
    return tl.ZoneRef(zone.center_lat, zone.center_lng, zone.radius_m) if zone else None


def _candidates(db: Session, user_id: str, now: datetime) -> list[tl.Candidate]:
    """이름 붙일 후보: 최근 며칠을 변환해 이름 없는 곳 가운데 자주 머문 곳을 찾는다."""
    start = now - timedelta(days=CANDIDATE_WINDOW_DAYS)
    segs = tl.convert(
        _points(db, user_id, start, now), _known(db, user_id), _zone_ref(db, user_id), (start, now)
    )
    return tl.frequent_unnamed(segs)


def _can_view(db: Session, viewer: User, group_id: str, target_id: str) -> bool:
    return viewer.id == target_id or viewer.id in service._parent_ids(db, group_id)


def _candidate_for(seg: tl.Seg, cands: list[tl.Candidate]) -> str | None:
    if seg.kind not in ("stay", "anomaly") or seg.place is not None or seg.lat is None:
        return None
    for c in cands:
        if tl.dist_m(seg.lat, seg.lng, c.lat, c.lng) <= tl.STAY_RADIUS_M:
            return c.id
    return None


def day_timeline(
    db: Session, viewer: User, group_id: str, target_id: str | None, day: date
) -> TimelineOut:
    service.ensure_enabled()
    target_id = target_id or viewer.id
    members = {u.id: u for u, _ in repo.group_users(db, group_id)}
    target = members.get(target_id)
    if target is None or not _can_view(db, viewer, group_id, target_id):
        raise ApiError(403, "location_forbidden", "이 사람의 이동 기록은 볼 수 없어요")
    out = TimelineOut(
        date=day.isoformat(),
        user_id=target.id,
        name=target.name,
        sharing=target.location_consent_at is not None,
        can_name=viewer.id == target.id,
        segments=[],
    )
    if not out.sharing:
        return out
    kst = _kst()
    now = datetime.now(UTC).astimezone(kst)
    start = datetime.combine(day, time(0), tzinfo=kst)
    end = min(start + timedelta(days=1), now)
    if end <= start:  # 아직 오지 않은 날
        return out
    segs = tl.convert(
        _points(db, target.id, start, end),
        _known(db, target.id),
        _zone_ref(db, target.id),
        (start, end),
    )
    cands = _candidates(db, target.id, now)
    out.segments = [
        SegmentOut(
            kind=s.kind,
            start=s.start,
            end=s.end,
            place=s.place,
            origin=s.origin,
            candidate_id=_candidate_for(s, cands),
        )
        for s in segs
    ]
    return out


def list_places(db: Session, user: User) -> PlacesOut:
    service.ensure_enabled()
    return _places_out(db, user)


def _places_out(db: Session, user: User) -> PlacesOut:
    now = datetime.now(UTC).astimezone(_kst())
    return PlacesOut(
        places=[PlaceOut(id=p.id, name=p.name) for p in repo.list_places(db, user.id)],
        candidates=[
            CandidateOut(
                id=c.id, label=f"자주 가는 곳 {i + 1}", visits=c.visits, last_seen=c.last_seen
            )
            for i, c in enumerate(_candidates(db, user.id, now))
        ],
    )


def name_place(db: Session, user: User, group_id: str, body: NamePlaceIn) -> PlacesOut:
    service.ensure_enabled()
    name = body.name.strip()
    if not name:
        raise bad_request("invalid_place_name", "장소 이름을 입력해 주세요")
    if len(repo.list_places(db, user.id)) >= MAX_PLACES:
        raise bad_request("too_many_places", f"장소는 {MAX_PLACES}곳까지 붙일 수 있어요")
    now = datetime.now(UTC).astimezone(_kst())
    cand = next((c for c in _candidates(db, user.id, now) if c.id == body.candidate_id), None)
    if cand is None:
        raise not_found("장소")
    db.add(LocationPlace(user_id=user.id, group_id=group_id, name=name, lat=cand.lat, lng=cand.lng))
    db.commit()
    return _places_out(db, user)


def delete_place(db: Session, user: User, place_id: str) -> PlacesOut:
    place = repo.get_place(db, user.id, place_id)
    if place is None:
        raise not_found("장소")
    db.delete(place)
    db.commit()
    return _places_out(
        db, user
    )  # 지우기는 스위치가 꺼져 있어도 된다(내 정보를 지우는 길은 항상 열어 둔다)
