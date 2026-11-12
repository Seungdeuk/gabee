"""대본형 가짜 모델 시험(L0): 응답 모양, Agent 가림, 대본 소진, 결정적 토큰, 기존 52건 대본의 형식."""

import httpx
import pytest

from app.shared.llm import chat_model, transport
from evals.agent_eval import adapter, fake_model
from evals.agent_eval.fake_model import (
    FAKE_TOKENS,
    FakeModel,
    Reply,
    ScriptExhausted,
    ToolUse,
    call,
    json_reply,
    round_of,
    say,
)

MAIN = {"system": "당신은 가비입니다", "messages": [], "model": "claude-haiku-5-5"}
BILLING = {**MAIN, "system": "가비의 가계(정산) 담당 에이전트입니다"}
CHAT = {**MAIN, "system": "가비의 가족 채팅 담당 에이전트입니다"}
SCHEDULE = {**MAIN, "output_config": {"format": {}}}


def test_the_agent_is_told_apart_by_the_request():
    assert fake_model.agent_of(MAIN) == "main"
    assert fake_model.agent_of(BILLING) == "billing"
    assert fake_model.agent_of(CHAT) == "family_chat"
    assert fake_model.agent_of(SCHEDULE) == "schedule"


def test_replies_have_the_anthropic_shape_that_the_app_parses():
    fake = FakeModel({"main": [call("list_items", {"limit": 2}), say("끝")]})
    first, last = fake(MAIN), fake(MAIN)
    message = chat_model.from_anthropic_reply(first)
    assert [(c["name"], c["args"]) for c in message.tool_calls] == [("list_items", {"limit": 2})]
    assert first["stop_reason"] == "tool_use" and first["model"] == "claude-haiku-5-5"
    assert chat_model.text_of(chat_model.from_anthropic_reply(last)) == "끝"
    assert transport.usage_of(first) == FAKE_TOKENS  # 토큰은 결정적이다


def test_several_tools_in_one_round_get_distinct_ids_and_json_replies_are_text():
    fake = FakeModel(
        {
            "main": [round_of(ToolUse("a"), ToolUse("b", {"x": 1}))],
            "schedule": [json_reply({"intent": "query"})],
        }
    )
    ids = [b["id"] for b in fake(MAIN)["content"]]
    assert len(set(ids)) == 2
    assert fake(SCHEDULE)["content"][0]["text"] == '{"intent": "query"}'


def test_each_agent_has_its_own_queue_and_the_last_text_repeats():
    fake = FakeModel(
        {"main": [say("메인")], "billing": [call("get_month_summary", {}), say("정산")]}
    )
    assert fake(BILLING)["stop_reason"] == "tool_use"
    assert fake(MAIN)["content"][0]["text"] == "메인"
    assert fake(BILLING)["content"][0]["text"] == "정산"
    assert fake(MAIN)["content"][0]["text"] == "메인"  # 마지막 글은 되풀이된다
    assert fake.agents == ["billing", "main", "billing", "main"] and fake.calls == 4


def test_a_script_that_ran_out_looks_like_a_model_failure_to_the_app():
    fake = FakeModel({"main": [call("x")]})
    fake(MAIN)
    with pytest.raises(ScriptExhausted) as raised:
        fake(MAIN)
    assert isinstance(raised.value, ValueError)  # 앱의 `except ValueError` 가 LLM 실패로 처리한다
    assert fake.exhausted == ["main"]
    with pytest.raises(ScriptExhausted):
        FakeModel({})(BILLING)


def test_token_usage_is_deterministic_and_can_be_overridden_per_reply_or_model():
    fake = FakeModel({"main": [say("a", tokens=(5, 7)), say("b")]}, tokens=(11, 13))
    assert transport.usage_of(fake(MAIN)) == (5, 7)
    assert transport.usage_of(fake(MAIN)) == (11, 13)
    again = FakeModel({"main": [say("a")]})
    assert (
        transport.usage_of(again(MAIN))
        == FAKE_TOKENS
        == transport.usage_of(FakeModel({"main": [say("a")]})(MAIN))
    )


def test_callable_arguments_are_evaluated_when_the_reply_is_made():
    seen = []

    def args(ctx):
        seen.append(type(ctx).__name__)
        return {"expense_id": "e1"}

    fake = FakeModel({"billing": [call("propose_delete_expense", args)]})
    assert seen == []
    block = fake(BILLING)["content"][0]
    assert block["input"] == {"expense_id": "e1"} and seen == ["ScriptContext"]


def test_tool_results_sent_back_are_recorded_as_evidence_that_the_tool_ran():
    fake = FakeModel({"main": [say("x")]})
    body = {
        **MAIN,
        "messages": [
            {"role": "user", "content": "q"},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "합계 60000"}],
            },
        ],
    }
    fake(body)
    assert fake.tool_results == {"t1": "합계 60000"}


def test_unknown_agent_names_and_malformed_replies_are_rejected():
    with pytest.raises(ValueError, match="Agent"):
        FakeModel({"ops": [say("x")]})
    with pytest.raises(ValueError):
        Reply()
    with pytest.raises(ValueError):
        Reply(text="a", tools=(ToolUse("x"),))


def test_installed_replaces_the_transport_function_and_restores_it():
    before = transport.post_messages
    fake = FakeModel({"main": [say("안녕")]})
    with fake_model.installed(fake):
        assert transport.post_messages is fake
        assert transport.post_messages(MAIN)["content"][0]["text"] == "안녕"
    assert transport.post_messages is before


def test_the_fake_never_touches_the_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("네트워크를 불렀다")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    with fake_model.installed(FakeModel({"main": [say("x")]})):
        assert transport.post_messages(MAIN, timeout=1, retry=True)["stop_reason"] == "end_turn"


@pytest.fixture(scope="module")
def legacy_cases():
    return adapter.load_legacy_cases()


def test_every_legacy_case_has_a_script_with_known_agents_and_no_script_error(legacy_cases):
    for lc in legacy_cases:
        script = fake_model.script_for(lc)
        assert script and set(script) <= set(fake_model.AGENTS), lc.case.id
        agent = "billing" if lc.checks.agent == "billing" else "main"
        assert agent in script and script[agent][-1].text is not None, lc.case.id


def test_hand_written_scripts_point_at_real_legacy_cases_and_the_right_agent(legacy_cases):
    by_id = {lc.case.id: lc for lc in legacy_cases}
    assert set(fake_model.LEGACY_SCRIPT_OVERRIDES) <= set(by_id)
    for case_id, script in fake_model.LEGACY_SCRIPT_OVERRIDES.items():
        assert ("billing" if by_id[case_id].checks.agent == "billing" else "main") in script


def test_the_default_answer_carries_the_expected_phrases_and_avoids_the_forbidden_ones(
    legacy_cases,
):
    by_id = {lc.case.id: lc for lc in legacy_cases}
    text = fake_model.default_script(by_id["b-total"])["billing"][-1].text
    assert "60,000" in text
    # 금지 문구가 기대 문구와 맞물려도 기대 문구를 지우거나 채점을 바꾸지 않고 오류로 알린다(없는 사례에서도 규칙은 같다)
    for lc in legacy_cases:
        script = fake_model.script_for(lc)
        final = (script.get("billing") or script["main"])[-1].text
        assert not any(t in final for t in lc.case.expect.answer.not_contains), lc.case.id
        assert not any(final.strip().endswith(t) for t in lc.checks.not_endswith), lc.case.id
