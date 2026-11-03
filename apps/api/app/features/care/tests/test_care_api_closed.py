"""돌봄 서버 API 스위치(CARE_API_ENABLED): 꺼져 있으면 남은 /care/* (위치)를 403 care_disabled 로 막고, 위치 동의 철회·조회는 열어 둔다.

돌봄 코드 시험은 conftest 가 켠 상태(CARE_API_ENABLED=true)에서 본다. 이 파일은 닫힌 상태를 본다.
데일리 체크 경로(/care/daily 등)는 지웠으니 닫힌 응답이 아니라 404 다.
"""

from datetime import UTC, datetime

import pytest

from app.shared.config import settings
from tests.helpers import signup


def _solo(client):
    h = signup(client, "혼자")
    client.post("/family-group/groups", json={"name": "우리 가족"}, headers=h)
    return h


def _point():
    return {
        "lat": 37.5665,
        "lng": 126.978,
        "accuracy_m": 12.5,
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def test_default_is_closed_in_settings():
    # conftest 가 시험용으로 환경 변수를 켜 두므로, 서비스 기본값은 설정 클래스의 필드 기본값으로 확인한다.
    assert type(settings).model_fields["care_api_enabled"].default is False


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/care/locations/latest", None),
        ("post", "/care/locations", {"points": [_point()]}),
    ],
)
def test_closed_blocks_remaining_care_endpoints(client, monkeypatch, method, path, body):
    monkeypatch.setattr(settings, "care_api_enabled", False)
    h = _solo(client)
    r = getattr(client, method)(path, headers=h, **({"json": body} if body is not None else {}))
    assert r.status_code == 403 and r.json()["code"] == "care_disabled", r.text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/care/daily"),
        ("get", "/care/records"),
        ("get", "/care/meals"),
        ("post", "/care/agent/chat"),
    ],
)
def test_deleted_daily_check_routes_are_gone(client, method, path):
    h = _solo(client)
    assert getattr(client, method)(path, headers=h).status_code in (404, 405)


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


def test_open_reaches_the_location_service(client, monkeypatch):
    # 스위치를 켜면 요청이 서비스까지 간다(위치 기능 스위치가 꺼져 있어 location_disabled 로 막힌다)
    monkeypatch.setattr(settings, "care_api_enabled", True)
    h = _solo(client)
    r = client.get("/care/locations/latest", headers=h)
    assert r.status_code == 403 and r.json()["code"] == "location_disabled", r.text
