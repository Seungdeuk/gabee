"""관리자 챗봇 서브 에이전트 모드(ADMIN_CHATBOT_SUBAGENTS). 실제 AI 는 부르지 않는다.

가짜 모델은 받은 지시문으로 누가 불렀는지(메인·서비스·운영·규칙 담당)를 가려 대본대로 답한다."""

import json

import pytest

from app.features.admin_knowledge import service, subagents
from app.shared.config import settings

PASSWORD = "Sunny-day-2026"
ASK = "/admin/knowledge/ask"
STREAM = "/admin/knowledge/ask/stream"
FAQ_HEADING = "## 관리자 계정은 어떻게 추가해?"


@pytest.fixture
def admin(client, monkeypatch) -> dict:
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
    monkeypatch.setattr(settings, "admin_user_ids", r.json()["user"]["id"])
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "admin_chatbot_subagents", True)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _role(system: str) -> str:
    for role, mark in (
        ("service", "서비스 담당입니다"),
        ("ops", "운영 담당입니다"),
        ("rules", "규칙 담당입니다"),
    ):
        if mark in system:
            return role
    return "main"


def _tool_use(name: str, args: dict) -> dict:
    return {"content": [{"type": "tool_use", "id": f"t-{name}", "name": name, "input": args}]}


def _text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _script(monkeypatch, replies: dict) -> list[dict]:
    """replies[role] 은 그 역할이 부를 때마다 차례로 돌려줄 답 목록(마지막 답은 계속 쓴다). 보낸 본문을 기록해 돌려준다."""
    sent: list[dict] = []
    counters: dict[str, int] = {}

    def post(body):
        role = _role(body["system"])
        sent.append({"role": role, **body})
        i = counters.get(role, 0)
        counters[role] = i + 1
        reply = replies[role][min(i, len(replies[role]) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(service, "_post", post)
    return sent


def _events(r) -> list[dict]:
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def test_switch_off_keeps_the_single_agent(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "admin_chatbot_subagents", False)
    sent = _script(monkeypatch, {"main": [_text("네.")]})
    assert client.post(ASK, json={"q": "회원 몇 명이야?"}, headers=admin).status_code == 200
    assert sent[0]["system"] == service.ASK_SYSTEM  # 스위치를 끄면 예전과 똑같다
    assert "members" in [t["name"] for t in sent[0]["tools"]]


def test_main_asks_the_service_agent_and_writes_the_answer(client, admin, monkeypatch):
    sent = _script(
        monkeypatch,
        {
            "main": [
                _tool_use("ask_service", {"question": "전체 회원 수"}),
                _text("**전체 회원은 1명이에요.**"),
            ],
            "service": [_tool_use("members", {}), _text("전체 회원 1명")],
        },
    )
    r = client.post(ASK, json={"q": "회원 몇 명이야?"}, headers=admin)
    assert r.status_code == 200 and r.json() == {"answer": "**전체 회원은 1명이에요.**"}
    main, sub = (
        [s for s in sent if s["role"] == "main"],
        [s for s in sent if s["role"] == "service"],
    )
    assert {t["name"] for t in main[0]["tools"]} == {"ask_service", "ask_ops", "ask_rules"}
    assert FAQ_HEADING not in main[0]["system"] and "담당에게 나눠 묻기" in main[0]["system"]
    sub_tools = {t["name"] for t in sub[0]["tools"]}
    assert (
        "members" in sub_tools and "server_requests" not in sub_tools
    )  # 서비스 담당은 서비스 도구만
    assert "전체 회원: 1명" in json.dumps(
        sub[1]["messages"], ensure_ascii=False
    )  # 숫자 도구 결과는 담당이 받는다
    assert "전체 회원 1명" in json.dumps(
        main[1]["messages"], ensure_ascii=False
    )  # 메인은 담당의 보고를 받는다


def test_ops_agent_gets_only_server_tools(client, admin, monkeypatch):
    sent = _script(
        monkeypatch,
        {
            "main": [_tool_use("ask_ops", {"question": "서버 상태"}), _text("확인할 수 없어요.")],
            "ops": [_text("확인할 수 없음")],
        },
    )
    assert client.post(ASK, json={"q": "서버 괜찮아?"}, headers=admin).status_code == 200
    ops = next(s for s in sent if s["role"] == "ops")
    assert {t["name"] for t in ops["tools"]} == {
        "server_requests",
        "server_errors",
    }


def test_rules_agent_gets_the_faq_and_no_tools(client, admin, monkeypatch):
    sent = _script(
        monkeypatch,
        {
            "main": [
                _tool_use("ask_rules", {"question": "관리자 추가 방법"}),
                _text("ADMIN_USER_IDS 에 넣어요."),
            ],
            "rules": [_text("서버 환경변수 ADMIN_USER_IDS 에 넣는다")],
        },
    )
    assert client.post(ASK, json={"q": "관리자 어떻게 추가해?"}, headers=admin).status_code == 200
    rules = next(s for s in sent if s["role"] == "rules")
    assert FAQ_HEADING in rules["system"] and rules["tools"] == []


def test_total_calls_stay_under_the_budget(client, admin, monkeypatch):
    # 메인도 담당도 끝없이 도구만 부르면: 합계가 상한에서 멈추고, 답이 없으니 503
    sent = _script(
        monkeypatch,
        {
            "main": [_tool_use("ask_service", {"question": "회원"})],
            "service": [_tool_use("members", {})],
        },
    )
    r = client.post(ASK, json={"q": "회원 몇 명이야?"}, headers=admin)
    assert r.status_code == 503 and r.json()["code"] == "llm_failed"
    assert len(sent) <= subagents.TOTAL_MAX_CALLS


def test_failed_agent_is_reported_as_unknown_and_main_still_answers(client, admin, monkeypatch):
    sent = _script(
        monkeypatch,
        {
            "main": [_tool_use("ask_service", {"question": "회원 수"}), _text("확인할 수 없어요.")],
            "service": [service.llm.LLMUnavailable("down")],
        },
    )
    r = client.post(ASK, json={"q": "회원 몇 명이야?"}, headers=admin)
    assert r.status_code == 200 and r.json()["answer"] == "확인할 수 없어요."
    main = [s for s in sent if s["role"] == "main"]
    assert "확인할 수 없음" in json.dumps(main[1]["messages"], ensure_ascii=False)


def test_stream_shows_the_agent_and_its_tool(client, admin, monkeypatch):
    _script(
        monkeypatch,
        {
            "main": [
                _tool_use("ask_service", {"question": "회원 수"}),
                _text("**전체 회원은 1명이에요.**"),
            ],
            "service": [_tool_use("members", {}), _text("전체 회원 1명")],
        },
    )
    events = _events(client.post(STREAM, json={"q": "회원 몇 명이야?"}, headers=admin))
    labels = [e["label"] for e in events if e["step"] == "tool"]
    assert labels == ["서비스 담당", "서비스 담당 · 회원 수 확인"]
    steps = [e["step"] for e in events]
    assert steps[:3] == ["received", "masked", "understand"] and steps[-2:] == ["write", "answer"]
