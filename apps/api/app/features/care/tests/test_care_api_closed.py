"""돌봄 서버 API 스위치(CARE_API_ENABLED): 꺼져 있으면 /care/* 를 403 care_disabled 로 막고, 위치 동의 철회·조회는 열어 둔다.

돌봄 코드 시험은 conftest 가 켠 상태(CARE_API_ENABLED=true)에서 본다. 이 파일은 닫힌 상태를 본다.
"""

import pytest

from app.shared.config import settings
from tests.helpers import signup


def _solo(client):
    h = signup(client, "혼자")
    client.post("/family-group/groups", json={"name": "우리 가족"}, headers=h)
    return h


def test_default_is_closed_in_settings():
    # conftest 가 시험용으로 환경 변수를 켜 두므로, 서비스 기본값은 설정 클래스의 필드 기본값으로 확인한다.
    assert type(settings).model_fields["care_api_enabled"].default is False


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/care/daily", None),
        ("post", "/care/items", {"name": "산책", "mode": "yesno", "time": "09:00"}),
        ("get", "/care/recommendations", None),
        ("get", "/care/meals", None),
        ("get", "/care/meal-log", None),
        ("get", "/care/locations/latest", None),
        ("get", "/care/summary/today", None),
        ("post", "/care/agent/chat", {"message": "오늘 어때?"}),
    ],
)
def test_closed_blocks_care_endpoints(client, monkeypatch, method, path, body):
    monkeypatch.setattr(settings, "care_api_enabled", False)
    h = _solo(client)
    r = getattr(client, method)(path, headers=h, **({"json": body} if body is not None else {}))
    assert r.status_code == 403 and r.json()["code"] == "care_disabled", r.text


def test_closed_keeps_location_consent_withdrawal_and_lookup_open(client, monkeypatch):
    h = _solo(client)
    monkeypatch.setattr(settings, "care_location_enabled", True)
    assert (
        client.put("/care/location/consent", json={"consent": True}, headers=h).status_code == 200
    )
    monkeypatch.setattr(settings, "care_api_enabled", False)
    assert client.get("/care/location/consent", headers=h).json()["consent"] is True
    assert (
        client.put("/care/location/consent", json={"consent": False}, headers=h).status_code == 200
    )
    assert client.get("/care/location/consent", headers=h).json()["consent"] is False


def test_open_allows_care_endpoints(client, monkeypatch):
    monkeypatch.setattr(settings, "care_api_enabled", True)
    h = _solo(client)
    assert client.get("/care/daily", headers=h).status_code == 200
