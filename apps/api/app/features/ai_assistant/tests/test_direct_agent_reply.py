"""탭 에이전트가 사용자에게 줄 답을 만들었으면 메인이 모델을 다시 부르지 않는다(모델 호출 1번 절약). 실제 LLM 은 부르지 않는다."""

import json

import pytest

from app.features.ai_assistant.knowledge import rag_chat
from app.shared.config import settings
from tests.ai_consent import enable_ai

SUB_ANSWER = "이번 달 지출은 총 0원이에요."


def _tool_use(*calls):
    return {
        "content": [
            {"type": "tool_use", "id": f"t{i}", "name": name, "input": args}
            for i, (name, args) in enumerate(calls)
        ]
    }


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


@pytest.fixture
def run(client, family, monkeypatch):
    """main_calls 를 세며 채팅을 한 번 돌린다. 메인은 첫 단계에서 지정한 도구들을 부르고, 결과를 받으면 '메인 최종 답' 으로 끝낸다."""
    a, _, group = family
    enable_ai(group["id"])
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    def go(first_calls, sub_tool="get_month_summary", sub_args=None, sub_text=SUB_ANSWER):
        counts = {"main": 0}

        def fake_post(body):
            if "가계(정산) 담당" in body["system"] or "돌봄 담당" in body["system"]:
                if len(body["messages"]) == 1:
                    return _tool_use((sub_tool, sub_args or {}))
                return _text(sub_text)
            counts["main"] += 1
            if len(body["messages"]) == 1:
                return _tool_use(*first_calls)
            return _text("메인 최종 답")

        monkeypatch.setattr(rag_chat, "_post", fake_post)
        reply = client.post("/ai-assistant/chat", json={"message": "질문"}, headers=a).json()
        return reply["reply"], counts["main"]

    return go


def test_single_agent_answer_is_returned_without_a_second_main_call(run):
    reply, main_calls = run([("ask_billing", {"question": "이번 달 지출"})])
    assert reply == SUB_ANSWER and main_calls == 1


def test_switch_off_keeps_the_old_behavior(run, monkeypatch):
    monkeypatch.setattr(settings, "assistant_direct_agent_reply", False)
    reply, main_calls = run([("ask_billing", {"question": "이번 달 지출"})])
    assert reply == "메인 최종 답" and main_calls == 2


def test_two_agent_calls_in_one_step_are_combined_by_main(run):
    reply, main_calls = run(
        [("ask_billing", {"question": "지출"}), ("ask_care", {"question": "돌봄"})]
    )
    assert reply == "메인 최종 답" and main_calls == 2


def test_other_tools_in_the_turn_keep_main_in_the_loop(run):
    reply, main_calls = run([("search_knowledge", {"query": "전기요금"})])
    assert reply == "메인 최종 답" and main_calls == 2  # 에이전트가 아니라서 해당 없음


def test_write_proposals_still_go_through_main(run):
    """쓰기 제안이 있으면 메인이 '확인 버튼을 눌러야 반영돼요'를 말해야 하므로 직통하지 않는다."""
    reply, main_calls = run(
        [("ask_billing", {"question": "마트 1만원 등록"})],
        sub_tool="propose_add_expense",
        sub_args={"title": "마트", "amount": 10000},
    )
    assert reply == "메인 최종 답" and main_calls == 2


def test_failed_agent_answer_still_goes_through_main(run):
    """에이전트가 도구 인자 오류 같은 문제로 답을 못 만들면(can_answer false) 메인이 이어서 안내한다."""
    from app.features.ai_assistant import agents
    from app.shared.llm.agent import AgentReply

    original = dict(agents.AGENTS)
    agents.AGENTS["ask_billing"] = (
        original["ask_billing"][0],
        lambda *a, **k: AgentReply("실패", can_answer=False),
    )
    try:
        reply, main_calls = run([("ask_billing", {"question": "이번 달 지출"})])
    finally:
        agents.AGENTS.update(original)
    assert reply == "메인 최종 답" and main_calls == 2


def test_direct_reply_keeps_tool_calls_for_the_room_visibility_check(client, family, monkeypatch):
    """직통으로 끝나도 어떤 도구가 불렸는지 기록은 남아야 한다(방 공유 판단 등이 이 기록을 쓴다)."""
    a, _, group = family
    enable_ai(group["id"])
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    def fake_post(body):
        if "가계(정산) 담당" in body["system"]:
            if len(body["messages"]) == 1:
                return _tool_use(("list_allowances", {}))
            return _text("용돈 장부는 비어 있어요.")
        return _tool_use(("ask_billing", {"question": "용돈"}))

    monkeypatch.setattr(rag_chat, "_post", fake_post)
    with __import__("app.shared.db", fromlist=["SessionLocal"]).SessionLocal() as db:
        from sqlalchemy import select

        from app.features.family_group.models import User

        user = db.scalars(select(User).where(User.name == "지민")).first()
        result = rag_chat.ask_guarded(
            db, user.id, group["id"], "용돈", feature="assistant_chat", user=user
        )
    assert result.answer == "용돈 장부는 비어 있어요."
    assert [c["name"] for c in result.tool_calls] == ["ask_billing"]
    assert [s["name"] for s in result.tool_calls[0]["agent_tool_calls"]] == ["list_allowances"]
    json.dumps(result.tool_calls)  # 기록이 직렬화 가능해야 한다
