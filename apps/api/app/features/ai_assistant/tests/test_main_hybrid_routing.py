"""메인 Agent 하이브리드 라우팅(docs/requirements/main-hybrid-routing.md).

판정 문장은 평가 사례(evals/agent_eval)와 겹치지 않는 일반화 문장이다. 사전에 평가 문장을 맞춰 넣지 않았는지 이 시험으로 확인한다."""

import json

import pytest

from app.features.ai_assistant import agents, routing
from app.features.ai_assistant.knowledge import rag_chat
from app.shared.config import settings
from app.shared.llm import eval_hook
from tests.ai_consent import enable_ai

ALL_AGENTS = {"ask_billing", "ask_family_chat", "ask_schedule"}


# ---- 1. 출처 판정 -------------------------------------------------------------


@pytest.mark.parametrize(
    "question, audience, allowed",
    [
        # 출처가 하나로 명시됨 → 그 담당만
        ("단톡에서 엄마가 말한 식당 이름 뭐였지?", "me", {"ask_family_chat"}),
        ("어제 대화에서 누가 차 가져온다고 했어?", "room", {"ask_family_chat"}),
        ("다음 달 캘린더에 비어 있는 주말 알려줘", "me", {"ask_schedule"}),
        ("아빠한테 보낸 부탁 수락됐어?", "me", {"ask_schedule"}),
        ("지난달 외식에 쓴 돈이 얼마야?", "me", {"ask_billing"}),
        ("이번 주 용돈 줬는지 봐 줘", "me", {"ask_billing"}),
        ("가족 할 일 목록에 남은 거 있어?", "me", {"ask_family_chat"}),
        ("일정 탭에 있는 할 일 보여줘", "me", {"ask_schedule"}),
        ("관리비 고지서에 납부 기한이 언제야?", "me", set()),
        # 가족방에서 목록을 말하지 않은 할 일은 가족 공동 목록
        ("우리 이번 주에 할 일 정리해 줘", "room", {"ask_family_chat"}),
        # 명시적 복합 → 언급된 담당 각각
        (
            "채팅에서 나온 병원 얘기랑 다음 주 일정 같이 봐 줘",
            "me",
            {"ask_family_chat", "ask_schedule"},
        ),
        ("정산 현황이랑 이번 주 스케줄 알려줘", "me", {"ask_billing", "ask_schedule"}),
    ],
)
def test_explicit_sources_limit_the_agents(question, audience, allowed):
    decision = routing.decide(question, audience)
    assert not decision.unclear
    assert decision.allowed == allowed


@pytest.mark.parametrize(
    "question, audience",
    [
        ("주말에 뭐 하기로 했지?", "me"),  # 출처 표현 없음
        ("내일 비 와?", "me"),
        ("오늘 해야 할 일 알려줘", "me"),  # 개인 채팅의 목록 미지정 할 일 → 기존 규칙대로 둘 다
        ("다음 주 일정이랑 할 일 알려줘", "me"),  # '일정'이 있어도 할 일 목록은 정해지지 않았다
        ("그거 일정에 넣어줘", "me"),  # 앞선 대화를 가리키는 말
        ("영수증 금액 지출로 등록해줘", "me"),  # 어느 탭에 쓸지는 앞뒤 말에 달린 쓰기 표현
        ("", "me"),
    ],
)
def test_unclear_questions_are_not_limited(question, audience):
    decision = routing.decide(question, audience)
    assert decision.unclear and decision.allowed is None
    assert all(decision.permits(name) for name in ALL_AGENTS)


def test_decision_rule_never_contains_the_question():
    question = "단톡에서 엄마가 말한 식당 이름 뭐였지?"
    decision = routing.decide(question, "me")
    assert question not in decision.rule and "식당" not in decision.rule


# ---- 2. 실행 게이트(_handle_calls) -------------------------------------------


def _handle(monkeypatch, mode: str, name: str, question: str, audience: str = "me"):
    received: list[str] = []

    def fake_call(db, group_id, user, agent_name, args, post, audience):
        received.append(agent_name)
        return {"answer": "ok", "can_answer": True}, [], [], []

    monkeypatch.setattr(agents, "call", fake_call)
    result = rag_chat.AskResult("", "ai")
    with eval_hook.recording() as rec:
        done = rag_chat._handle_calls(
            [{"id": "t1", "name": name, "args": {"question": "넘김 질문"}}],
            db=None,
            group_id="g",
            user=None,
            audience=audience,
            with_agents=True,
            post=lambda body: {},
            result=result,
            seen=set(),
            refs={},
            question=question,
            route=routing.decide(question, audience),
            route_mode=mode,
        )
    return received, done, rec


CHAT_ONLY = "단톡에서 엄마가 말한 식당 이름 뭐였지?"


def test_off_mode_calls_the_agent_and_records_nothing(monkeypatch):
    received, done, rec = _handle(monkeypatch, "off", "ask_schedule", CHAT_ONLY)
    assert received == ["ask_schedule"]
    assert rec.routing_blocks == []


def test_shadow_mode_calls_the_agent_and_records_the_would_be_block(monkeypatch):
    received, done, rec = _handle(monkeypatch, "shadow", "ask_schedule", CHAT_ONLY)
    assert received == ["ask_schedule"]
    assert json.loads(done.outputs[0][1])["answer"] == "ok"
    assert rec.routing_blocks == [
        {"stage": "main", "mode": "shadow", "name": "ask_schedule", "rule": "explicit:chat_history"}
    ]


def test_enforce_mode_does_not_call_the_agent_and_answers_the_model(monkeypatch):
    received, done, rec = _handle(monkeypatch, "enforce", "ask_schedule", CHAT_ONLY)
    assert received == []
    call_id, text, is_error = done.outputs[0]
    assert call_id == "t1" and is_error is False
    assert json.loads(text) == {"answer": routing.BLOCKED_TEXT, "can_answer": False}
    assert done.direct_answer is None  # 막은 호출의 글을 사용자에게 바로 보내지 않는다
    assert [b["mode"] for b in rec.routing_blocks] == ["enforce"]


def test_enforce_mode_lets_allowed_and_unclear_calls_through(monkeypatch):
    received, _, rec = _handle(monkeypatch, "enforce", "ask_family_chat", CHAT_ONLY)
    assert received == ["ask_family_chat"] and rec.routing_blocks == []
    received, _, rec = _handle(monkeypatch, "enforce", "ask_schedule", "주말에 뭐 하기로 했지?")
    assert received == ["ask_schedule"] and rec.routing_blocks == []


def test_direct_room_schedule_block_still_comes_first():
    """1:1 방의 일정 차단은 agents.call 안의 기존 규칙이다. 라우팅이 허용해도 그 규칙은 그대로 적용된다."""
    result = rag_chat.AskResult("", "ai")
    done = rag_chat._handle_calls(
        [{"id": "t1", "name": "ask_schedule", "args": {"question": "내일 일정"}}],
        db=None,
        group_id="g",
        user=None,
        audience="direct",
        with_agents=True,
        post=lambda body: {},
        result=result,
        seen=set(),
        refs={},
        question="내일 일정 알려줘",
        route=routing.decide("내일 일정 알려줘", "direct"),
        route_mode="enforce",
    )
    assert json.loads(done.outputs[0][1])["answer"] == "1:1 대화에서는 아직 일정을 다루지 않아요"


# ---- 3. 모델에 보내는 도구 목록 -----------------------------------------------


@pytest.fixture
def sent_tools(client, family, monkeypatch):
    """/ai-assistant/chat 을 부르고 메인 모델 첫 요청에 실린 담당 도구 이름을 돌려준다."""
    a, _b, group = family
    enable_ai(group["id"])
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    def go(mode: str, message: str) -> set[str]:
        monkeypatch.setattr(settings, "main_routing_mode", mode)
        seen: list[set[str]] = []

        def fake_post(req):
            seen.append({t["name"] for t in req.get("tools", [])} & ALL_AGENTS)
            return {"content": [{"type": "text", "text": "답"}]}

        monkeypatch.setattr(rag_chat, "_post", fake_post)
        r = client.post("/ai-assistant/chat", json={"message": message}, headers=a)
        assert r.status_code == 200, r.text
        return seen[0]

    return go


def test_tool_list_is_unchanged_in_off_and_shadow(sent_tools):
    assert sent_tools("off", CHAT_ONLY) == ALL_AGENTS
    assert sent_tools("shadow", CHAT_ONLY) == ALL_AGENTS


def test_tool_list_is_narrowed_in_enforce(sent_tools):
    assert sent_tools("enforce", CHAT_ONLY) == {"ask_family_chat"}
    assert sent_tools("enforce", "관리비 고지서에 납부 기한이 언제야?") == set()
    assert sent_tools("enforce", "주말에 뭐 하기로 했지?") == ALL_AGENTS


def test_invalid_mode_is_rejected():
    from pydantic import ValidationError

    from app.shared.config import Settings

    with pytest.raises(ValidationError):
        Settings(main_routing_mode="block")
