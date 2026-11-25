"""Agent 경로의 출력 토큰 상한 `settings.agent_max_output_tokens`(AGENT_MAX_OUTPUT_TOKENS, 기본 10000)를 실제 요청 본문으로 확인한다(2026-11-25).

여섯 경로: 메인, 메인 웹 검색, 소통 Agent, 소통 Agent 의 대화 분석, 일정 Agent, 정산 Agent. 범위 밖(일반 상한 2048, 돌봄 등 `run_agent` 기본 1024, 답 검증,
일정 제안 2500, 답장 400·주제 500, 통화 300)은 그대로다. 실제 Anthropic 은 부르지 않는다(가짜 전송·가짜 `complete_json`).
"""

from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.features.ai_assistant.knowledge import rag_chat, verify
from app.features.billing import agent as billing_agent
from app.features.family_chat import agent as fc_agent
from app.features.family_chat import ai_service
from app.features.family_group.models import User
from app.shared.config import Settings, settings
from app.shared.db import SessionLocal
from app.shared.llm import agent as llm_agent
from app.shared.llm import proposals
from tests.ai_consent import enable_ai, enable_ai_for_user

APP = Path(rag_chat.__file__).resolve().parents[3]  # app/


def _text(text="끝"):
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}


def _user(db, name="지민"):
    return db.scalars(select(User).where(User.name == name)).first()


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _path_main(group, bodies):
    with SessionLocal() as db:
        rag_chat.ask(db, group["id"], "안녕", post=lambda b: (bodies.append(b), _text())[1])


def _path_main_web(group, bodies):
    settings.web_search_enabled = True
    with SessionLocal() as db:
        rag_chat.ask(
            db,
            group["id"],
            "내일 서울 날씨 어때?",
            post=lambda b: (bodies.append(b), _text())[1],
            web=True,
        )


def _path_family_chat(group, bodies):
    with SessionLocal() as db:
        fc_agent.ask(
            db,
            group["id"],
            _user(db),
            "할 일 알려 줘",
            post=lambda b: (bodies.append(b), _text())[1],
            guarded=False,
        )


def _path_billing(group, bodies):
    proposals.reset()
    with SessionLocal() as db:
        billing_agent.ask(
            db,
            group["id"],
            _user(db),
            "이번 달 지출 알려 줘",
            post=lambda b: (bodies.append(b), _text())[1],
            guarded=False,
        )


PATHS = {
    "main": _path_main,
    "main_web": _path_main_web,
    "family_chat": _path_family_chat,
    "billing": _path_billing,
}


@pytest.fixture
def world(client, family, monkeypatch):
    a, _, group = family
    enable_ai(group["id"])
    enable_ai_for_user()
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "web_search_enabled", False)
    return client, a, group


@pytest.mark.parametrize("name", sorted(PATHS))
def test_each_agent_path_requests_the_shared_limit_by_default(world, monkeypatch, name):
    _, _, group = world
    bodies = []
    PATHS[name](group, bodies)
    assert bodies and {b["max_tokens"] for b in bodies} == {10000}


@pytest.mark.parametrize("name", sorted(PATHS))
def test_an_env_style_override_reaches_each_agent_request(world, monkeypatch, name):
    _, _, group = world
    monkeypatch.setattr(settings, "agent_max_output_tokens", 7777)
    bodies = []
    PATHS[name](group, bodies)
    assert bodies and {b["max_tokens"] for b in bodies} == {7777}


def test_the_main_web_search_path_also_sends_the_web_tool(world):
    _, _, group = world
    bodies = []
    _path_main_web(group, bodies)
    assert any(t.get("name") == "web_search" for t in bodies[0]["tools"])  # 웹 경로로 실제 갔다


# ---------- 대화 분석 ----------
def test_the_analysis_call_follows_the_override(world, monkeypatch):
    client, a, group = world
    sent = []

    def post(url, json=None, headers=None, timeout=None):
        sent.append(json["max_tokens"])
        return _Resp(
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"summary": "요약", "important_messages": [], "schedule_candidates": [], '
                        '"todo_candidates": [], "replies": [], "topics": []}',
                    }
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 7, "output_tokens": 10},
                "model": "m-x",
            }
        )

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(settings, "ai_request_cooldown_seconds", 0)
    for i in range(3):
        assert (
            client.post(
                "/family-chat/messages", json={"text": f"메시지 {i}"}, headers=a
            ).status_code
            == 201
        )
    assert client.post("/family-chat/ai/analysis", json={}, headers=a).status_code == 200
    monkeypatch.setattr(settings, "agent_max_output_tokens", 7777)
    client.post("/family-chat/messages", json={"text": "새 메시지"}, headers=a)
    assert client.post("/family-chat/ai/analysis", json={}, headers=a).status_code == 200
    assert sent == [10000, 7777]


# ---------- 범위 밖은 그대로 ----------
def test_out_of_scope_limits_are_unchanged():
    assert Settings().anthropic_max_tokens == 2048  # 일반 호출(ANTHROPIC_MAX_TOKENS)
    import inspect

    assert inspect.signature(llm_agent.run_agent).parameters["max_tokens"].default == 1024
    assert inspect.signature(llm_agent.ask_agent).parameters["max_tokens"].default is None
    assert verify.VERIFY_MAX_TOKENS == 2048  # 답 검증
    assert "max_tokens=400" in Path(ai_service.__file__).read_text("utf-8")  # 답장 추천
    assert "max_tokens=500" in Path(ai_service.__file__).read_text("utf-8")  # 대화 주제
    assert "max_tokens=2500" in (APP / "features/schedule/agent/suggest.py").read_text("utf-8")
    assert "max_tokens=300" in (APP / "features/schedule/call_talk/service.py").read_text("utf-8")


def test_an_agent_call_that_gives_no_limit_such_as_care_keeps_the_run_agent_default():
    """정산만 호출에서 상한을 명시한다. 돌봄 등 상한을 주지 않는 `ask_agent` 호출은 기존 1024 그대로다."""
    seen = []

    def post(body):
        seen.append(body["max_tokens"])
        return _text()

    llm_agent.ask_agent("시스템", "질문", [], post=post)
    assert seen == [1024]


# ---------- 설정 검증 ----------
def test_the_setting_defaults_to_10000_and_reads_the_environment(monkeypatch):
    monkeypatch.delenv("AGENT_MAX_OUTPUT_TOKENS", raising=False)
    assert Settings(_env_file=None).agent_max_output_tokens == 10000
    monkeypatch.setenv("AGENT_MAX_OUTPUT_TOKENS", "4321")
    assert Settings(_env_file=None).agent_max_output_tokens == 4321


@pytest.mark.parametrize("bad", ["0", "-1", "128001", "abc", "1.5"])
def test_the_setting_rejects_values_outside_the_models_range(monkeypatch, bad):
    monkeypatch.setenv("AGENT_MAX_OUTPUT_TOKENS", bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_the_setting_accepts_the_models_maximum(monkeypatch):
    monkeypatch.setenv(
        "AGENT_MAX_OUTPUT_TOKENS", "128000"
    )  # Haiku 5.5 의 최대 출력(Models API 확인)
    assert Settings(_env_file=None).agent_max_output_tokens == 128000
