"""이동 기록 타임라인 · 장소 이름 붙이기 API 시험."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.features.location.models import LocationPlace, LocationPoint
from app.shared.config import settings
from app.shared.db import SessionLocal

M = 1 / 111320.0
HOME = (37.0, 127.0)
CAFE = (37.008, 127.016)
KST = timedelta(hours=9)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "location_enabled", True)


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _consent(client, headers):
    assert (
        client.put("/location/consent", json={"consent": True}, headers=headers).status_code == 200
    )


def _add_points(user_id: str, group_id: str, place, start_utc: datetime, minutes: int) -> None:
    """place 둘레에서 1분마다 점을 DB 에 바로 넣는다(UTC 시각)."""
    with SessionLocal() as db:
        for k in range(minutes):
            wobble = ((k * 7) % 5 - 2) * 10 * M
            db.add(
                LocationPoint(
                    user_id=user_id,
                    group_id=group_id,
                    lat=place[0] + wobble,
                    lng=place[1] + wobble,
                    accuracy_m=10.0,
                    recorded_at=start_utc + timedelta(minutes=k),
                    received_at=start_utc,
                )
            )
        db.commit()


def _group_id(client, headers) -> str:
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


def _kst_day(days_ago: int) -> tuple[str, datetime]:
    """KST 기준 며칠 전 날짜와 그날 KST 오전 9시에 해당하는 UTC 시각."""
    kst_now = datetime.now(UTC) + KST
    day = (kst_now - timedelta(days=days_ago)).date()
    start_utc = datetime(day.year, day.month, day.day, 0, 0, tzinfo=UTC)  # KST 09:00 = UTC 00:00
    return day.isoformat(), start_utc


def _timeline(client, headers, day, user_id=None):
    params = {"date": day, **({"user_id": user_id} if user_id else {})}
    return client.get("/location/timeline", params=params, headers=headers)


def test_requires_login_and_switch(client, family):
    a, _, _ = family
    day, _ = _kst_day(1)
    assert client.get("/location/timeline", params={"date": day}).status_code == 401
    assert _timeline(client, a, day).status_code == 503  # 스위치 꺼짐
    assert client.get("/location/places", headers=a).status_code == 503


def test_timeline_has_stays_with_no_coordinates_and_no_record_gaps(client, family, on):
    a, b, _ = family
    uid, gid = _me(client, b), _group_id(client, b)
    _consent(client, b)
    day, nine_kst = _kst_day(2)
    _add_points(uid, gid, HOME, nine_kst, 60)  # KST 09:00~10:00
    res = _timeline(client, b, day)
    assert res.status_code == 200
    body = res.json()
    assert body["sharing"] is True and body["can_name"] is True and body["user_id"] == uid
    kinds = [s["kind"] for s in body["segments"]]
    assert kinds == ["no_record", "stay", "no_record"]  # 앞뒤 빈 시간은 기록 없음
    stay = body["segments"][1]
    assert stay["place"] is None  # 이름 없는 곳
    assert "lat" not in str(body) and "lng" not in str(body)  # 좌표 필드가 없다


def test_parent_can_see_child_timeline_but_child_cannot_see_parent(client, family, on):
    a, b, _ = family
    ua, ub, gid = _me(client, a), _me(client, b), _group_id(client, a)
    _consent(client, a)
    _consent(client, b)
    day, nine_kst = _kst_day(2)
    _add_points(ub, gid, HOME, nine_kst, 30)
    assert _timeline(client, a, day, ub).status_code == 200  # 소유자(부모)는 가족 것을 본다
    denied = _timeline(client, b, day, ua)
    assert denied.status_code == 403 and denied.json()["code"] == "location_forbidden"


def test_other_family_cannot_view(client, family, other_family, on):
    a, b, _ = family
    ub = _me(client, b)
    day, _ = _kst_day(1)
    assert _timeline(client, other_family, day, ub).status_code == 403


def test_person_without_consent_gets_empty_timeline(client, family, on):
    a, b, _ = family
    day, _ = _kst_day(1)
    body = _timeline(client, a, day, _me(client, b)).json()
    assert body["sharing"] is False and body["segments"] == []


def test_future_day_is_empty(client, family, on):
    a, _, _ = family
    _consent(client, a)
    future = (datetime.now(UTC) + KST + timedelta(days=3)).date().isoformat()
    assert _timeline(client, a, future).json()["segments"] == []


def _visits(user_id: str, gid: str, place, days=(1, 2, 3, 4)):
    for d in days:
        _, nine_kst = _kst_day(d)
        _add_points(user_id, gid, place, nine_kst, 30)


def test_frequent_place_becomes_candidate_and_naming_labels_the_timeline(client, family, on):
    _, b, _ = family
    uid, gid = _me(client, b), _group_id(client, b)
    _consent(client, b)
    _visits(uid, gid, CAFE)
    places = client.get("/location/places", headers=b).json()
    assert places["places"] == [] and len(places["candidates"]) == 1
    cand = places["candidates"][0]
    assert cand["label"] == "자주 가는 곳 1" and cand["visits"] == 4

    day, _ = _kst_day(2)
    seg = next(s for s in _timeline(client, b, day).json()["segments"] if s["kind"] == "stay")
    assert seg["candidate_id"] == cand["id"] and seg["place"] is None

    named = client.post(
        "/location/places", json={"candidate_id": cand["id"], "name": " 단골 카페 "}, headers=b
    )
    assert named.status_code == 201
    assert [p["name"] for p in named.json()["places"]] == ["단골 카페"] and named.json()[
        "candidates"
    ] == []
    seg = next(s for s in _timeline(client, b, day).json()["segments"] if s["kind"] == "stay")
    assert seg["place"] == "단골 카페" and seg["candidate_id"] is None


def test_parent_sees_child_named_places_but_cannot_name_for_child(client, family, on):
    a, b, _ = family
    ub, gid = _me(client, b), _group_id(client, b)
    _consent(client, b)
    _visits(ub, gid, CAFE)
    cand = client.get("/location/places", headers=b).json()["candidates"][0]
    client.post("/location/places", json={"candidate_id": cand["id"], "name": "학원 앞"}, headers=b)
    day, _ = _kst_day(2)
    body = _timeline(client, a, day, ub).json()
    assert body["can_name"] is False
    assert any(s["place"] == "학원 앞" for s in body["segments"])
    # 부모가 자기 이름으로 자녀의 후보를 이름 붙이려 해도 자기 후보가 아니라서 찾지 못한다
    assert (
        client.post(
            "/location/places", json={"candidate_id": cand["id"], "name": "x"}, headers=a
        ).status_code
        == 404
    )


def test_naming_validation_and_limits(client, family, on):
    _, b, _ = family
    uid, gid = _me(client, b), _group_id(client, b)
    _consent(client, b)
    _visits(uid, gid, CAFE)
    cand = client.get("/location/places", headers=b).json()["candidates"][0]
    assert (
        client.post(
            "/location/places", json={"candidate_id": cand["id"], "name": ""}, headers=b
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/location/places", json={"candidate_id": cand["id"], "name": "가" * 21}, headers=b
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/location/places", json={"candidate_id": cand["id"], "name": "   "}, headers=b
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/location/places", json={"candidate_id": "nope", "name": "집"}, headers=b
        ).status_code
        == 404
    )
    with SessionLocal() as db:  # 20곳을 채운 뒤에는 더 붙일 수 없다
        for i in range(20):
            db.add(
                LocationPlace(
                    user_id=uid, group_id=gid, name=f"곳{i}", lat=36.0 + i * 0.01, lng=126.0
                )
            )
        db.commit()
    full = client.post(
        "/location/places", json={"candidate_id": cand["id"], "name": "또"}, headers=b
    )
    assert full.status_code == 400 and full.json()["code"] == "too_many_places"


def test_delete_place_only_own_and_works_when_switch_is_off(client, family, on, monkeypatch):
    a, b, _ = family
    ub, gid = _me(client, b), _group_id(client, b)
    _consent(client, b)
    _visits(ub, gid, CAFE)
    cand = client.get("/location/places", headers=b).json()["candidates"][0]
    pid = client.post(
        "/location/places", json={"candidate_id": cand["id"], "name": "카페"}, headers=b
    ).json()["places"][0]["id"]
    assert client.delete(f"/location/places/{pid}", headers=a).status_code == 404  # 남의 장소
    monkeypatch.setattr(settings, "location_enabled", False)
    assert (
        client.delete(f"/location/places/{pid}", headers=b).status_code == 200
    )  # 지우기는 스위치와 무관
    with SessionLocal() as db:
        assert not list(db.scalars(select(LocationPlace).where(LocationPlace.user_id == ub)))


def test_withdrawing_consent_deletes_named_places(client, family, on):
    _, b, _ = family
    ub, gid = _me(client, b), _group_id(client, b)
    _consent(client, b)
    _visits(ub, gid, CAFE)
    cand = client.get("/location/places", headers=b).json()["candidates"][0]
    client.post("/location/places", json={"candidate_id": cand["id"], "name": "카페"}, headers=b)
    client.put("/location/consent", json={"consent": False}, headers=b)
    with SessionLocal() as db:
        assert not list(db.scalars(select(LocationPlace).where(LocationPlace.user_id == ub)))
        assert not list(db.scalars(select(LocationPoint).where(LocationPoint.user_id == ub)))
