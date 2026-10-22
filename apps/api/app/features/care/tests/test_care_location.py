"""돌봄 위치 공유: 가입 시 동의, 동의한 사람만 보내기, 가족만 조회, 철회하면 삭제, 보관 기간."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.features.care.models import CareLocation
from app.shared.db import SessionLocal
from app.shared.location_consent import LocationConsentEvent
from tests.helpers import signup


def _point(lat=37.5665, lng=126.978, minutes_ago=1, accuracy=12.5):
    at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return {"lat": lat, "lng": lng, "accuracy_m": accuracy, "recorded_at": at.isoformat()}


def _consent(client, headers, value=True):
    r = client.put("/care/location/consent", json={"consent": value}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _send(client, headers, *points):
    return client.post("/care/locations", json={"points": list(points)}, headers=headers)


def _latest(client, headers):
    return {
        m["name"]: m
        for m in client.get("/care/locations/latest", headers=headers).json()["members"]
    }


def _rows(user_id=None):
    with SessionLocal() as db:
        q = select(CareLocation)
        if user_id:
            q = q.where(CareLocation.user_id == user_id)
        return list(db.scalars(q))


def _my_id(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def test_consent_defaults_to_off_and_can_be_given_at_signup(client):
    plain = signup(client, "동의 안 함")
    assert client.get("/care/location/consent", headers=plain).json() == {
        "consent": False,
        "since": None,
    }

    r = client.post(
        "/family-group/users",
        json={"name": "가입 때 동의", "role": "child", "location_consent": True},
    )
    assert r.status_code == 201 and r.json()["user"]["location_consent"] is True
    h = {"X-Gyeot-Token": r.json()["token"]}
    state = client.get("/care/location/consent", headers=h).json()
    assert state["consent"] is True and state["since"] is not None
    assert client.get("/family-group/me", headers=h).json()["location_consent"] is True

    with SessionLocal() as db:
        events = list(
            db.scalars(
                select(LocationConsentEvent).where(
                    LocationConsentEvent.user_id == r.json()["user"]["id"]
                )
            )
        )
    assert [(e.consent, e.source) for e in events] == [(True, "signup")]


def test_consent_changes_are_logged_once_per_change(client, family):
    a, _, _ = family
    uid = _my_id(client, a)
    _consent(client, a, True)
    _consent(client, a, True)  # 같은 상태 반복은 이력을 늘리지 않는다
    _consent(client, a, False)
    with SessionLocal() as db:
        events = list(
            db.scalars(
                select(LocationConsentEvent)
                .where(LocationConsentEvent.user_id == uid)
                .order_by(LocationConsentEvent.at)
            )
        )
    assert [(e.consent, e.source) for e in events] == [(True, "care"), (False, "care")]


def test_only_consenting_members_can_send_locations(client, family):
    a, _, _ = family
    denied = _send(client, a, _point())
    assert denied.status_code == 403 and denied.json()["code"] == "consent_required"
    assert _rows() == []
    _consent(client, a)
    ok = _send(client, a, _point(), _point(37.57, 126.98, minutes_ago=2))
    assert ok.status_code == 201 and ok.json() == {"saved": 2, "skipped": 0}


def test_family_sees_only_consenting_members_with_latest_point(client, family):
    a, b, _ = family
    _consent(client, a)
    _send(client, a, _point(37.1, 127.1, minutes_ago=30), _point(37.5665, 126.978, minutes_ago=3))
    seen = _latest(client, b)  # 수진이 본다
    assert seen["지민"]["sharing"] is True and (seen["지민"]["lat"], seen["지민"]["lng"]) == (
        37.5665,
        126.978,
    )
    assert (
        seen["지민"]["minutes_ago"] in (3, 4)
        and seen["지민"]["is_me"] is False
        and seen["지민"]["accuracy_m"] == 12.5
    )
    # 동의하지 않은 수진은 좌표 없이 sharing=false
    assert (
        seen["수진"]["sharing"] is False
        and seen["수진"]["lat"] is None
        and seen["수진"]["is_me"] is True
    )
    assert client.get("/care/locations/latest", headers=b).json()["retention_days"] == 7


def test_consenting_member_without_a_point_has_no_coordinates(client, family):
    a, b, _ = family
    _consent(client, a)
    seen = _latest(client, b)["지민"]
    assert seen["sharing"] is True and seen["lat"] is None and seen["recorded_at"] is None


def test_other_families_cannot_see_the_location(client, family):
    a, _, _ = family
    _consent(client, a)
    _send(client, a, _point())
    outsider = signup(client, "남의 집")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    names = _latest(client, outsider)
    assert set(names) == {"남의 집"}
    assert all(m["lat"] is None for m in names.values())


def test_revoking_deletes_stored_locations_immediately(client, family):
    a, b, _ = family
    uid = _my_id(client, a)
    _consent(client, a)
    _send(client, a, _point(), _point(minutes_ago=5))
    assert len(_rows(uid)) == 2
    _consent(client, a, False)
    assert _rows(uid) == []
    seen = _latest(client, b)["지민"]
    assert seen["sharing"] is False and seen["lat"] is None
    # 다시 동의해도 이전 위치는 돌아오지 않는다
    _consent(client, a, True)
    assert _latest(client, b)["지민"]["lat"] is None


def test_revoking_one_member_keeps_others_data(client, family):
    a, b, _ = family
    _consent(client, a)
    _consent(client, b)
    _send(client, a, _point())
    _send(client, b, _point(35.1, 129.0))
    _consent(client, a, False)
    assert len(_rows(_my_id(client, b))) == 1
    assert _latest(client, a)["수진"]["lat"] == 35.1


def test_validation_and_old_or_future_points(client, family):
    a, _, _ = family
    _consent(client, a)
    assert _send(client, a, _point(lat=91)).status_code == 422
    assert _send(client, a, _point(lng=-181)).status_code == 422
    assert client.post("/care/locations", json={"points": []}, headers=a).status_code == 422
    assert (
        client.post("/care/locations", json={"points": [_point()] * 51}, headers=a).status_code
        == 422
    )

    old = _point(minutes_ago=60 * 24 * 8)  # 8일 전: 보관 기간(7일) 밖
    future = _point(minutes_ago=-10)  # 10분 뒤: 시계 오차 허용(5분) 밖
    skew = _point(minutes_ago=-3)  # 3분 뒤: 허용
    r = _send(client, a, old, future, skew, _point())
    assert r.json() == {"saved": 2, "skipped": 2}


def test_old_rows_are_purged_when_new_points_arrive(client, family):
    a, b, _ = family
    uid_b = _my_id(client, b)
    _consent(client, b)
    with SessionLocal() as db:
        db.add(
            CareLocation(
                id="oldrow",
                user_id=uid_b,
                lat=1.0,
                lng=2.0,
                recorded_at=datetime.now(UTC) - timedelta(days=9),
                received_at=datetime.now(UTC) - timedelta(days=9),
            )
        )
        db.commit()
    assert len(_rows(uid_b)) == 1
    _consent(client, a)
    _send(client, a, _point())  # 누가 보내든 보관 기간이 지난 위치는 지워진다
    assert _rows(uid_b) == []


def test_user_without_a_group_cannot_send(client):
    h = signup(client, "혼자")
    _consent(client, h)
    r = _send(client, h, _point())
    assert r.status_code == 400 and r.json()["code"] == "no_group"


def test_coordinates_never_appear_in_logs(client, family, caplog):
    a, b, _ = family
    _consent(client, a)
    with caplog.at_level(logging.DEBUG):
        _send(client, a, _point(37.123456, 127.654321))
        _latest(client, b)
    assert "37.123456" not in caplog.text and "127.654321" not in caplog.text
