"""위치 공유 기능 스위치(CARE_LOCATION_ENABLED): 꺼져 있으면 저장·조회·동의와 에이전트의 위치 도구를 막고, 철회는 열어 둔다."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.features.care import agent
from app.features.care.models import CareLocation
from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.helpers import signup

TOOL = "get_family_locations"


def _point():
    return {
        "lat": 37.5665,
        "lng": 126.978,
        "accuracy_m": 12.5,
        "recorded_at": datetime.now(UTC).isoformat(),
    }


def _solo(client):
    """그룹을 만든 한 사람. (헤더, 그룹) 을 돌려준다."""
    h = signup(client, "혼자")
    group = client.post("/family-group/groups", json={"name": "우리 가족"}, headers=h).json()
    return h, group


def _rows():
    with SessionLocal() as db:
        return list(db.scalars(select(CareLocation)))


def _tool_names(client, h, group):
    me = client.get("/family-group/me", headers=h).json()["id"]
    with SessionLocal() as db:
        return {t.name for t in agent.build_tools(db, group["id"], db.get(User, me))}


def test_location_is_off_by_default():
    assert settings.care_location_enabled is False


def test_disabled_blocks_send_latest_and_giving_consent(client, monkeypatch):
    monkeypatch.setattr(settings, "care_location_enabled", False)
    h, _ = _solo(client)
    for r in (
        client.post("/care/locations", json={"points": [_point()]}, headers=h),
        client.get("/care/locations/latest", headers=h),
        client.put("/care/location/consent", json={"consent": True}, headers=h),
    ):
        assert r.status_code == 403 and r.json()["code"] == "location_disabled", r.text
    assert client.get("/care/location/consent", headers=h).json()["consent"] is False
    assert _rows() == []


def test_revoking_consent_still_works_and_deletes_stored_points(client, monkeypatch):
    h, _ = _solo(client)
    monkeypatch.setattr(settings, "care_location_enabled", True)
    assert (
        client.put("/care/location/consent", json={"consent": True}, headers=h).status_code == 200
    )
    assert client.post("/care/locations", json={"points": [_point()]}, headers=h).status_code == 201
    assert len(_rows()) == 1
    monkeypatch.setattr(settings, "care_location_enabled", False)  # 그 뒤 기능을 껐다
    assert client.get("/care/location/consent", headers=h).json()["consent"] is True
    r = client.put("/care/location/consent", json={"consent": False}, headers=h)
    assert r.status_code == 200 and r.json()["consent"] is False
    assert _rows() == []  # 철회하면 저장된 내 위치가 지워진다


def test_agent_never_has_the_location_tool(client, monkeypatch):
    """돌봄 에이전트는 위치 도구를 주지 않는다(스위치를 켜도). 다시 살릴 때는 도구를 되돌려야 한다."""
    h, group = _solo(client)
    for on in (False, True):
        monkeypatch.setattr(settings, "care_location_enabled", on)
        assert TOOL not in _tool_names(client, h, group)
        assert "지금 사용할 수 없" in agent.system_prompt("혼자")
