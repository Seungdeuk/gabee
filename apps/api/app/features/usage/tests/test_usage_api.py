"""체류시간 저장: 본인 것만, 탭별 하루 합계에 더하고, app 줄에 앱 전체 합계와 실행 횟수를 둔다."""

from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import signup

URL = "/usage/report"


def _today() -> str:
    from app.features.usage.service import today

    return today(datetime.now(UTC)).isoformat()


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _rows(user_id: str) -> dict[str, tuple[int, int]]:
    from app.features.usage.models import UsageDaily
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        return {
            r.tab: (r.seconds, r.opens)
            for r in db.query(UsageDaily).filter(UsageDaily.user_id == user_id)
        }


@pytest.fixture(autouse=True)
def _clean(client):
    from app.features.usage.models import UsageDaily
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        db.query(UsageDaily).delete()
        db.commit()


def test_requires_login(client):
    assert client.post(URL, json={"day": _today(), "tabs": {"chat": 10}}).status_code == 401


def test_saves_tabs_and_app_total(client):
    h = signup(client, "민수")
    body = {"day": _today(), "opens": 1, "tabs": {"chat": 120, "schedule": 30}}
    r = client.post(URL, json=body, headers=h)
    assert r.status_code == 204, r.text
    assert _rows(_me(client, h)) == {"chat": (120, 0), "schedule": (30, 0), "app": (150, 1)}


def test_reports_add_up(client):
    h = signup(client, "민수")
    client.post(URL, json={"day": _today(), "opens": 1, "tabs": {"chat": 100}}, headers=h)
    client.post(URL, json={"day": _today(), "opens": 1, "tabs": {"chat": 50, "my": 10}}, headers=h)
    assert _rows(_me(client, h)) == {"chat": (150, 0), "my": (10, 0), "app": (160, 2)}


def test_zero_seconds_are_skipped(client):
    h = signup(client, "민수")
    client.post(URL, json={"day": _today(), "tabs": {"chat": 0, "care": 5}}, headers=h)
    assert _rows(_me(client, h)) == {"care": (5, 0), "app": (5, 0)}
    client.post(URL, json={"day": _today(), "tabs": {}}, headers=h)  # 아무것도 없으면 그대로
    assert _rows(_me(client, h)) == {"care": (5, 0), "app": (5, 0)}


def test_one_report_is_capped_and_day_total_is_capped(client):
    h = signup(client, "민수")
    uid = _me(client, h)
    client.post(URL, json={"day": _today(), "tabs": {"chat": 86400}}, headers=h)
    assert _rows(uid)["chat"] == (4 * 3600, 0)  # 한 번에 최대 4시간
    for _ in range(6):
        client.post(URL, json={"day": _today(), "tabs": {"chat": 86400}}, headers=h)
    assert _rows(uid)["chat"][0] == 86400  # 하루 최대 24시간


def test_user_without_family_can_send(client):
    h = signup(client, "지민")
    assert client.post(URL, json={"day": _today(), "tabs": {"my": 3}}, headers=h).status_code == 204


def test_saves_only_for_caller(client, family):
    a, b, _ = family
    client.post(URL, json={"day": _today(), "tabs": {"chat": 7}}, headers=a)
    assert _rows(_me(client, b)) == {}


@pytest.mark.parametrize(
    "body",
    [
        {"day": "today", "tabs": {"chat": 1}},  # 날짜 형식
        {"day": None, "tabs": {"chat": 1}},
        {"tabs": {"chat": 1}},  # 날짜 없음
        {"day": "2026-01-01", "tabs": {"settings": 1}},  # 모르는 탭
        {"day": "2026-01-01", "tabs": {"chat": -1}},
        {"day": "2026-01-01", "tabs": {"chat": 86401}},
        {"day": "2026-01-01", "opens": 21, "tabs": {"chat": 1}},
        {"day": "2026-01-01", "tabs": "chat"},
    ],
)
def test_invalid_body_is_rejected(client, body):
    h = signup(client, "민수")
    assert client.post(URL, json=body, headers=h).status_code == 422, body


def test_day_out_of_range_is_rejected(client):
    from app.features.usage.service import today

    h = signup(client, "민수")
    base = today(datetime.now(UTC))
    old = (base - timedelta(days=8)).isoformat()
    future = (base + timedelta(days=2)).isoformat()
    for day in (old, future):
        r = client.post(URL, json={"day": day, "tabs": {"chat": 1}}, headers=h)
        assert (r.status_code, r.json()["code"]) == (422, "usage_day_out_of_range"), day
    ok = (base - timedelta(days=7)).isoformat()
    assert client.post(URL, json={"day": ok, "tabs": {"chat": 1}}, headers=h).status_code == 204
    assert _rows(_me(client, h)) == {"chat": (1, 0), "app": (1, 0)}
