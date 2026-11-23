"""새 표 3개가 아직 없는 DB(코드가 DB 보다 먼저 배포된 경우)에서도 서버는 시작하고, AI 추억 API 만 503 이며,
가족 나가기·채팅 사진 삭제·가족 삭제 같은 기존 기능은 그대로 동작해야 한다(정리 훅은 표가 없으면 건너뛴다).
tests/test_schema_gate.py 와 같은 방식으로 표를 지워 "마이그레이션 전 DB" 를 흉내 낸다."""

import io

import pytest
from PIL import Image
from sqlalchemy import text

from app.shared.config import settings
from app.shared.db import engine
from app.shared.schema import monitor
from tests.helpers import signup

MEMORY_TABLES = ("photo_analysis_exclusions", "member_memory_consents", "family_memory_settings")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "schema_recheck_ready_seconds", 0)
    monkeypatch.setattr(settings, "schema_recheck_not_ready_seconds", 0)
    monkeypatch.setattr(settings, "schema_force_min_interval_seconds", 0)
    monitor.reset()
    yield
    monitor.reset()


def _drop_memory_tables():
    with engine.begin() as conn:
        for name in MEMORY_TABLES:
            conn.execute(text(f"DROP TABLE {name}"))


def _photo(client, headers):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_only_memory_api_is_blocked_and_existing_features_keep_working(client, family):
    a, b, group = family
    message_id = _photo(client, b)
    _drop_memory_tables()

    blocked = client.get("/family-memory/settings", headers=a)
    assert blocked.status_code == 503 and blocked.json()["code"] == "schema_not_ready"
    assert (
        client.put("/family-memory/consent", json={"consent": False}, headers=b).status_code == 503
    )

    # 기존 기능은 영향이 없다: 채팅 조회, 사진 삭제(정리 훅이 표가 없어 건너뜀)
    assert client.get("/family-chat/messages", headers=a).status_code == 200
    assert client.delete(f"/family-chat/messages/{message_id}", headers=b).status_code == 200

    report = client.get("/health/db").json()
    assert report["features"]["family_memory"]["ready"] is False
    assert report["features"]["family_chat"]["ready"] is True


def test_leaving_family_and_family_purge_work_without_memory_tables(client, family):
    a, b, group = family
    _drop_memory_tables()
    assert client.post("/family-group/groups/me/leave", headers=b).status_code == 204
    assert (
        client.post("/family-group/groups/me/leave", headers=a).status_code == 204
    )  # 혼자 남은 소유자: 가족 삭제
    again = signup(client, "새사람")
    assert client.post(
        "/family-group/groups", json={"name": "새 가족"}, headers=again
    ).status_code in (200, 201)
