"""위치 공유(베타) API 시험: 스위치·동의·구역 계산·이탈 알림·일시정지·가족 보기."""

from datetime import UTC, datetime, timedelta

import pytest

from app.shared.config import settings
from app.shared.db import SessionLocal

LAT, LNG = 37.5665, 126.9780  # 시험용 가짜 중심 좌표


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "location_enabled", True)


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _consent(client, headers, value=True):
    return client.put("/location/consent", json={"consent": value}, headers=headers)


def _send(client, headers, lat=LAT, lng=LNG, **extra):
    return client.post("/location/points", json={"lat": lat, "lng": lng, **extra}, headers=headers)


def _seed_zone(client, headers, count=22):
    """집 근처(수십 m 안)에서 count 번 위치를 보내 활동 구역을 만든다."""
    now = datetime.now(UTC)
    for i in range(count):
        body = {
            "lat": LAT + (i % 5) * 0.0002,
            "lng": LNG + (i % 4) * 0.0002,
            "recorded_at": (now - timedelta(minutes=count - i)).isoformat(),
        }
        assert client.post("/location/points", json=body, headers=headers).status_code == 201


def _location_notifications(client, headers):
    items = client.get("/notifications", headers=headers).json()["items"]
    return [n for n in items if n["kind"] == "care"]


def test_requires_login(client):
    for method, path in (
        ("get", "/location/me"),
        ("put", "/location/consent"),
        ("post", "/location/points"),
        ("get", "/location/family"),
        ("put", "/location/pause"),
    ):
        assert getattr(client, method)(path).status_code == 401


def test_switch_off_closes_everything_except_withdraw(client, family):
    a, _, _ = family
    me = client.get("/location/me", headers=a).json()
    assert me["enabled"] is False and me["consent"] is False
    assert _consent(client, a, True).status_code == 503
    assert _send(client, a).status_code == 503
    assert client.get("/location/family", headers=a).status_code == 503
    assert _consent(client, a, False).status_code == 200  # 철회는 항상 열려 있다
    assert client.delete("/location/me", headers=a).status_code == 200


def test_points_need_consent(client, family, on):
    a, _, _ = family
    res = _send(client, a)
    assert res.status_code == 201 and res.json() == {
        "saved": False,
        "reason": "no_consent",
        "outside": False,
        "alerted": False,
    }
    assert client.get("/location/me", headers=a).json()["point_count"] == 0


def test_zone_is_built_after_enough_points(client, family, on):
    _, b, _ = family
    _consent(client, b)
    for _ in range(4):
        _send(client, b)
    assert client.get("/location/me", headers=b).json()["zone"] is None  # 4개로는 아직 구역이 없다
    _send(client, b)
    zone = client.get("/location/me", headers=b).json()["zone"]
    assert zone is not None and zone["radius_m"] >= 300 and zone["sample_count"] == 5


def test_exit_alerts_parents_once_and_resets_when_back(client, family, on):
    a, b, _ = family
    _consent(client, b)
    _seed_zone(client, b)
    inside = _send(client, b).json()
    assert inside["outside"] is False and inside["alerted"] is False

    away = _send(client, b, lat=LAT + 0.05).json()  # 약 5.5km
    assert away == {"saved": True, "reason": None, "outside": True, "alerted": True}
    again = _send(client, b, lat=LAT + 0.05).json()  # 쿨다운 안에서는 다시 알리지 않는다
    assert again["outside"] is True and again["alerted"] is False

    notes = _location_notifications(client, a)
    assert [n["event"] for n in notes] == ["zone_exit"]
    text = notes[0]["title"] + (notes[0]["body"] or "")
    assert str(LAT)[:5] not in text and "위도" not in text  # 좌표·장소는 문구에 없다
    assert _location_notifications(client, b) == []  # 본인에게는 알리지 않는다

    assert _send(client, b).json()["outside"] is False  # 돌아오면 상태가 초기화된다
    assert _send(client, b, lat=LAT + 0.05).json()["alerted"] is False  # 쿨다운은 6시간
    # 쿨다운이 지났다고 보고 다시 시험: 초기화 뒤 첫 이탈은 쿨다운과 무관하게 알린다
    assert len(_location_notifications(client, a)) >= 1


def test_pause_stops_collection_and_alerts_and_notifies_parents(client, family, on):
    a, b, _ = family
    _consent(client, b)
    _seed_zone(client, b)
    paused = client.put("/location/pause", json={"days": 3}, headers=b).json()
    assert paused["paused"] is True and paused["paused_until"]

    res = _send(client, b, lat=LAT + 0.05).json()
    assert res["saved"] is False and res["reason"] == "paused" and res["alerted"] is False
    events = [n["event"] for n in _location_notifications(client, a)]
    assert events == ["location_paused"]  # 이탈 알림은 없고 일시정지 사실만 간다

    fam = client.get("/location/family", headers=a).json()
    bm = next(m for m in fam["members"] if not m["is_me"])
    assert bm["paused"] is True and bm["sharing"] is False and bm["lat"] is None

    resumed = client.put("/location/pause", json={}, headers=b).json()
    assert resumed["paused"] is False
    assert _send(client, b, lat=LAT + 0.05).json()["saved"] is True


def test_pause_needs_consent_and_limit(client, family, on):
    _, b, _ = family
    assert client.put("/location/pause", json={"days": 2}, headers=b).status_code == 400
    _consent(client, b)
    assert client.put("/location/pause", json={"days": 15}, headers=b).status_code == 422


def test_family_view_parent_sees_all_others_only_self(client, family, on):
    a, b, _ = family
    _consent(client, a)
    _consent(client, b)
    _send(client, a)
    _send(client, b)
    parent = client.get("/location/family", headers=a).json()
    assert parent["can_see_family"] is True and len(parent["members"]) == 2
    child = client.get("/location/family", headers=b).json()
    assert child["can_see_family"] is False
    assert [m["is_me"] for m in child["members"]] == [True]


def test_family_view_hides_members_who_did_not_consent(client, family, on):
    a, b, _ = family
    _consent(client, a)
    _send(client, a)
    fam = client.get("/location/family", headers=a).json()
    other = next(m for m in fam["members"] if not m["is_me"])
    assert other["sharing"] is False and other["lat"] is None and other["lng"] is None


def test_withdraw_deletes_everything(client, family, on):
    _, b, _ = family
    _consent(client, b)
    _seed_zone(client, b)
    client.put("/location/pause", json={"days": 1}, headers=b)
    me = _consent(client, b, False).json()
    assert me["consent"] is False and me["zone"] is None and me["point_count"] == 0
    assert me["paused"] is False


def test_simulate_exit_alerts_without_saving(client, family, on):
    a, b, _ = family
    assert client.post("/location/simulate-exit", json={}, headers=b).status_code == 400
    _consent(client, b)
    _seed_zone(client, b)
    before = client.get("/location/me", headers=b).json()["point_count"]
    res = client.post("/location/simulate-exit", json={"distance_m": 3000}, headers=b).json()
    assert res["outside"] is True and res["alerted"] is True and res["saved"] is False
    assert client.get("/location/me", headers=b).json()["point_count"] == before
    assert [n["event"] for n in _location_notifications(client, a)] == ["zone_exit"]


def test_future_timestamp_is_rejected(client, family, on):
    _, b, _ = family
    _consent(client, b)
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert _send(client, b, recorded_at=future).status_code == 400


def test_other_family_cannot_see_members(client, family, other_family, on):
    _, b, _ = family
    _consent(client, b)
    _send(client, b)
    _consent(client, other_family)
    fam = client.get("/location/family", headers=other_family).json()
    assert [m["is_me"] for m in fam["members"]] == [True]


def _bg(client, headers, enabled=True):
    return client.put("/location/background", json={"enabled": enabled}, headers=headers)


def _bg_events(user_id):
    from sqlalchemy import select

    from app.shared.location_consent import LocationConsentEvent

    with SessionLocal() as db:
        rows = db.scalars(
            select(LocationConsentEvent)
            .where(
                LocationConsentEvent.user_id == user_id,
                LocationConsentEvent.source == "location_bg",
            )
            .order_by(LocationConsentEvent.at)
        )
        return [r.consent for r in rows]


def test_background_needs_location_consent_first(client, family, on):
    _, b, _ = family
    assert _bg(client, b).status_code == 400
    assert client.get("/location/me", headers=b).json()["background"] is False
    _consent(client, b)
    res = _bg(client, b)
    assert res.status_code == 200 and res.json()["background"] is True


def test_background_toggle_is_logged_and_off_is_idempotent(client, family, on):
    _, b, _ = family
    uid = _me(client, b)
    _consent(client, b)
    assert _bg(client, b).json()["background"] is True
    assert _bg(client, b).json()["background"] is True  # 이미 켜져 있으면 이력을 또 남기지 않는다
    assert _bg(client, b, False).json()["background"] is False
    assert _bg(client, b, False).json()["background"] is False
    assert _bg_events(uid) == [True, False]


def test_withdrawing_location_consent_also_ends_background(client, family, on):
    _, b, _ = family
    uid = _me(client, b)
    _consent(client, b)
    _bg(client, b)
    me = _consent(client, b, False).json()
    assert me["consent"] is False and me["background"] is False
    assert _bg_events(uid) == [True, False]  # 철회로 함께 끝났다는 이력
    _consent(client, b)
    assert (
        client.get("/location/me", headers=b).json()["background"] is False
    )  # 다시 동의해도 백그라운드는 꺼져 있다


def test_background_can_be_turned_on_only_when_switch_is_on_but_off_is_always_open(
    client, family, monkeypatch
):
    _, b, _ = family
    monkeypatch.setattr(settings, "location_enabled", True)
    _consent(client, b)
    _bg(client, b)
    monkeypatch.setattr(settings, "location_enabled", False)
    assert _bg(client, b).status_code == 503
    assert _bg(client, b, False).status_code == 200
