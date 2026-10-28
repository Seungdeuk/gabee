"""경로 스위치(DISABLED_AI_ROUTES) 시험. 임시 SQLite·가짜 httpx 만 쓴다(실제 외부 호출 없음)."""

import httpx
import pytest

from app.shared import route_switch
from app.shared.config import settings
from tests.helpers import signup


@pytest.fixture
def no_outbound(monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append((a, k))
        raise AssertionError("외부 호출이 일어나면 안 된다")

    monkeypatch.setattr(httpx, "post", boom)
    return calls


def _set(monkeypatch, value):
    monkeypatch.setattr(settings, "disabled_ai_routes", value)


def test_empty_setting_disables_nothing(client, monkeypatch):
    _set(monkeypatch, "")
    assert client.get("/health").status_code == 200
    assert (
        client.post("/ai-assistant/knowledge/items", json={}).status_code == 401
    )  # 라우터까지 도달


def test_listed_route_gets_503_without_reaching_router_or_outbound(
    client, no_outbound, monkeypatch
):
    _set(monkeypatch, "POST /ai-assistant/knowledge/items")
    h = signup(client)
    r = client.post("/ai-assistant/knowledge/items", json={"title": "x", "body_md": "y"}, headers=h)
    assert r.status_code == 503
    assert r.json() == {"code": "route_disabled", "message": "이 기능은 지금 잠시 꺼져 있어요"}
    assert "Traceback" not in r.text
    assert no_outbound == []
    # 인증 없이도 (라우터에 닿기 전에) 같은 응답
    assert client.post("/ai-assistant/knowledge/items", json={}).status_code == 503


def test_response_matches_common_error_shape(client, monkeypatch):
    _set(monkeypatch, "GET /health")
    r = client.get("/health")
    assert r.status_code == 503 and r.headers["content-type"].startswith("application/json")
    assert set(r.json()) == {"code", "message"}


def test_wildcard(client, monkeypatch):
    _set(monkeypatch, "POST /ai-assistant/knowledge/*")
    assert client.post("/ai-assistant/knowledge/ask", json={}).status_code == 503
    assert client.post("/ai-assistant/knowledge/items/abc/summary").status_code == 503
    assert client.post("/ai-assistant/chat", json={}).status_code == 401  # 다른 경로는 영향 없음


def test_method_is_distinguished_and_case_insensitive(client, monkeypatch):
    _set(monkeypatch, "post /ai-assistant/knowledge/items")
    assert client.post("/ai-assistant/knowledge/items", json={}).status_code == 503
    assert client.get("/ai-assistant/knowledge/items").status_code == 401  # GET 은 통과


def test_trailing_slash_and_other_paths_unaffected(client, monkeypatch):
    _set(monkeypatch, "POST /ai-assistant/knowledge/items")
    assert client.post("/ai-assistant/knowledge/items/", json={}).status_code == 503
    assert client.get("/health").status_code == 200
    assert client.post("/ai-assistant/knowledge/itemsX", json={}).status_code != 503


def test_invalid_entries_are_ignored_and_valid_ones_still_apply(client, monkeypatch):
    _set(monkeypatch, "garbage, GET, FOO /x, POST nopath, , POST /ai-assistant/chat")
    assert client.post("/ai-assistant/chat", json={}).status_code == 503
    assert client.get("/health").status_code == 200


def test_parse_rules():
    assert route_switch.parse_rules("") == []
    assert route_switch.parse_rules(" post /a/* , GET  /b ") == [("POST", "/a/*"), ("GET", "/b")]
    assert route_switch.parse_rules("x,y z,POST") == []
