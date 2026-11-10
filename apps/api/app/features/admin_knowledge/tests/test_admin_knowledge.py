"""통합관리자 챗봇: 관리자만, 키 없음, 실패. 시험에서는 실제 AI 를 부르지 않는다."""

from types import SimpleNamespace

import pytest

from app.features.admin_knowledge import live, service
from app.shared.config import settings
from app.shared.db import SessionLocal

PASSWORD = "Sunny-day-2026"
ASK = "/admin/knowledge/ask"


def _login(client) -> tuple[dict, str]:
    body = {
        "login_id": "jimin_kim",
        "password": PASSWORD,
        "email": "jimin_kim@example.com",
        "name": "김지민",
    }
    assert client.post("/family-group/auth/signup", json=body).status_code == 201
    r = client.post(
        "/family-group/auth/login", json={"login_id": "jimin_kim", "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]["id"]


@pytest.fixture
def admin(client, monkeypatch) -> dict:
    headers, user_id = _login(client)
    monkeypatch.setattr(settings, "admin_user_ids", user_id)
    return headers


def _fake_llm(monkeypatch, reply="아니요. 알림은 가지 않습니다."):
    seen = {}

    def complete(prompt, system=None, max_tokens=0):
        seen["prompt"], seen["system"] = prompt, system
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(service.llm, "available", lambda: True)
    monkeypatch.setattr(service.llm, "complete", complete)
    return seen


def test_needs_login_and_admin_list(client, monkeypatch):
    assert client.post(ASK, json={"q": "공지"}).status_code == 401
    headers, _ = _login(client)
    monkeypatch.setattr(settings, "admin_user_ids", "")
    r = client.post(ASK, json={"q": "공지"}, headers=headers)
    assert r.status_code == 403 and r.json()["code"] == "operator_required"


def test_sends_question_with_faq_to_claude(client, admin, monkeypatch):
    seen = _fake_llm(monkeypatch)
    r = client.post(ASK, json={"q": "공지 올리면 알림이 가?"}, headers=admin)
    assert r.status_code == 200 and r.json() == {"answer": "아니요. 알림은 가지 않습니다."}
    assert seen["prompt"].endswith("관리자 질문: 공지 올리면 알림이 가?")
    assert "현재 숫자:" in seen["prompt"]
    assert "공지 올리면 사용자에게 알림이 가?" in seen["system"]  # faq.md 를 함께 준다
    assert "일상 질문" in seen["system"]


def test_without_key_says_so(client, admin, monkeypatch):
    monkeypatch.setattr(service.llm, "available", lambda: False)
    r = client.post(ASK, json={"q": "공지 알림"}, headers=admin)
    assert r.status_code == 503 and r.json()["code"] == "ai_key_missing"


def test_call_failure_is_503(client, admin, monkeypatch):
    _fake_llm(monkeypatch, service.llm.LLMUnavailable("실패"))
    r = client.post(ASK, json={"q": "공지 알림"}, headers=admin)
    assert r.status_code == 503 and r.json()["code"] == "llm_failed"


def test_numbers_match_the_admin_screen(client, admin):
    screen = client.get("/admin/service/groups", headers=admin).json()
    members = client.get("/admin/service/members", headers=admin).json()
    with SessionLocal() as db:
        text = live.live_summary(db)
    assert f"가족 그룹: {screen['total']}개" in text
    assert f"구성원이 1명뿐인 가족: {screen['single_member']}곳" in text
    assert f"전체 회원: {members['total']}명" in text


def test_personal_data_is_not_sent_to_claude(client, admin, monkeypatch):
    seen = _fake_llm(monkeypatch)
    client.post("/family-group/groups", json={"name": "비밀스러운가족"}, headers=admin)
    me = client.get("/admin/service/me", headers=admin).json()
    r = client.post(ASK, json={"q": "가족 몇 개야?"}, headers=admin)
    assert r.status_code == 200
    for secret in ("비밀스러운가족", "김지민", "jimin_kim", "@example.com", me["id"]):
        assert secret not in seen["prompt"]


def test_error_message_and_trace_id_are_not_sent(monkeypatch):
    item = SimpleNamespace(
        event_type="KeyError",
        method="GET",
        route="/notices",
        status=500,
        occurrences=3,
        kind="server_error",
        message="비밀 메시지",
        last_trace_id="trace123",
    )
    out = SimpleNamespace(errors_enabled=True, items=[item])
    monkeypatch.setattr(live.query_service, "errors", lambda *a: out)
    lines = live._errors(None)
    assert "KeyError" in lines[0] and "/notices" in lines[0] and "3회" in lines[0]
    assert "비밀 메시지" not in lines[0] and "trace123" not in lines[0]


def test_collection_off_is_not_reported_as_zero(client, admin):
    with SessionLocal() as db:
        text = live.live_summary(db)
    assert "수집이 꺼져 있어" in text
    assert "5xx 오류: 0건" not in text


def test_one_failed_section_does_not_stop_the_rest(client, admin, monkeypatch):
    def boom(db):
        raise RuntimeError("표 없음")

    monkeypatch.setattr(live, "SECTIONS", (("회원", boom), ("가족", live._groups)))
    with SessionLocal() as db:
        text = live.live_summary(db)
    assert "회원: 확인할 수 없음" in text and "가족 그룹:" in text
