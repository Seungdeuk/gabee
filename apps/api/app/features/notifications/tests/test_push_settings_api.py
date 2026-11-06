"""푸시 설정 조회·저장 API(/notifications/push-settings) 시험."""

from sqlalchemy import func, select

from app.shared.db import SessionLocal
from app.shared.push_models import PushSetting

URL = "/notifications/push-settings"
DEFAULTS = {
    "enabled": True,
    "preview_mode": "full",
    "muted_kinds": [],
    "quiet_start": None,
    "quiet_end": None,
}


def _rows() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(PushSetting))


def test_requires_login(client):
    assert client.get(URL).status_code == 401
    assert client.put(URL, json=DEFAULTS).status_code == 401


def test_defaults_when_no_row(client, family):
    a, _b, _group = family
    r = client.get(URL, headers=a)
    assert r.status_code == 200 and r.json() == DEFAULTS
    assert _rows() == 0  # 조회만으로는 줄을 만들지 않는다


def test_put_then_get_roundtrip(client, family):
    a, _b, _group = family
    body = {
        "enabled": False,
        "preview_mode": "sender",
        "muted_kinds": ["billing", "schedule"],
        "quiet_start": "22:00",
        "quiet_end": "07:00",
    }
    put = client.put(URL, json=body, headers=a)
    assert put.status_code == 200, put.text
    expected = {**body, "quiet_start": "22:00:00", "quiet_end": "07:00:00"}
    assert put.json() == expected
    assert client.get(URL, headers=a).json() == expected
    assert client.put(URL, json=DEFAULTS, headers=a).json() == DEFAULTS  # 다시 저장하면 덮어쓴다
    assert _rows() == 1


def test_invalid_values_are_422(client, family):
    a, _b, _group = family
    for bad in (
        {**DEFAULTS, "preview_mode": "loud"},
        {**DEFAULTS, "muted_kinds": ["no-such-kind"]},
        {**DEFAULTS, "quiet_start": "25:00", "quiet_end": "07:00"},
    ):
        assert client.put(URL, json=bad, headers=a).status_code == 422, bad


def test_chat_is_a_kind_users_can_mute_for_push(client, family):
    """소통(chat)은 알림함 분류는 아니지만 푸시 설정에서는 끌 수 있다."""
    a, _b, _group = family
    r = client.put(URL, json={**DEFAULTS, "muted_kinds": ["chat", "billing"]}, headers=a)
    assert r.status_code == 200, r.text
    assert client.get(URL, headers=a).json()["muted_kinds"] == ["chat", "billing"]


def test_quiet_hours_need_both_or_neither(client, family):
    a, _b, _group = family
    for bad in (
        {**DEFAULTS, "quiet_start": "22:00"},
        {**DEFAULTS, "quiet_end": "07:00"},
    ):
        assert client.put(URL, json=bad, headers=a).status_code == 422, bad


def test_settings_are_per_user(client, family):
    a, b, _group = family
    client.put(URL, json={**DEFAULTS, "enabled": False}, headers=a)
    assert client.get(URL, headers=a).json()["enabled"] is False
    assert client.get(URL, headers=b).json() == DEFAULTS
