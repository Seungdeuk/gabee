"""하위 Agent 까지 포함한 통합 프롬프트 해시 시험(L0, 가짜 모델·외부 호출 없음)."""

import pytest

from evals.agent_eval import agent_hashes, cli


def test_the_hashes_are_deterministic_and_main_is_the_manifest_hash():
    first = agent_hashes.agent_hashes()
    assert first == agent_hashes.agent_hashes()
    assert tuple(first) == agent_hashes.AGENTS
    assert (
        first["main"] == cli._prompt_hash()
    )  # dev 108 manifest 와 같은 방식의 값(계산을 바꾸지 않았다)
    assert len(set(first.values())) == len(first)  # 서로 다른 Agent 는 다른 해시다
    assert agent_hashes.integrated_hash(first) == agent_hashes.integrated_hash()


def test_the_hashes_do_not_depend_on_the_day_the_prompt_is_built(monkeypatch):
    """가족 대화·정산 시스템 프롬프트에는 오늘 날짜가 들어 있다. 실제 날짜가 바뀌어도 해시는 같아야 한다(고정 시계로 계산)."""
    from app.features.billing import agent as billing
    from app.features.family_chat import agent as family_chat
    from evals.agent_eval import clock

    seen = {}
    for name, module in (("family_chat", family_chat), ("billing", billing)):
        original = module.system_prompt

        def spy(*args, _name=name, _original=original):
            text = _original(*args)
            seen[_name] = (clock.is_frozen(), text)
            return text

        monkeypatch.setattr(module, "system_prompt", spy)
    agent_hashes.agent_hashes()
    reference_day = clock.REFERENCE_NOW.date().isoformat()
    for name in ("family_chat", "billing"):
        frozen, text = seen[name]
        assert frozen, f"{name} 프롬프트를 고정 시계 밖에서 만들었다(해시가 날짜마다 바뀐다)"
        assert reference_day in text, f"{name} 프롬프트의 날짜가 고정 기준일이 아니다"


def _changed(monkeypatch, target, name, value):
    before = agent_hashes.agent_hashes()
    monkeypatch.setattr(target, name, value)
    after = agent_hashes.agent_hashes()
    return before, after


def test_a_family_chat_prompt_change_moves_only_its_hash_and_the_integrated_one(monkeypatch):
    """isolation-02·inject-03 처럼 하위 Agent 프롬프트만 바뀐 경우: manifest 해시(main)는 그대로인데 통합 해시는 바뀐다."""
    from app.features.family_chat import agent as family_chat

    original = family_chat.system_prompt
    before, after = _changed(
        monkeypatch, family_chat, "system_prompt", lambda: original() + " 추가"
    )
    assert (
        before["main"] == after["main"]
    )  # 기존 manifest 해시는 이 변화를 못 본다(그래서 통합 해시가 필요하다)
    assert before["family_chat"] != after["family_chat"]
    assert before["billing"] == after["billing"] and before["schedule"] == after["schedule"]
    assert agent_hashes.integrated_hash(before) != agent_hashes.integrated_hash(after)


def test_a_family_chat_tool_description_change_is_seen(monkeypatch):
    from app.features.family_chat import agent as family_chat

    original = family_chat.build_tools

    def patched(*args, **kwargs):
        tools = original(*args, **kwargs)
        tools[0].description += " (바뀜)"
        return tools

    before, after = _changed(monkeypatch, family_chat, "build_tools", patched)
    assert before["family_chat"] != after["family_chat"] and before["main"] == after["main"]


def test_a_billing_prompt_or_tool_change_is_seen(monkeypatch):
    from app.features.billing import agent as billing

    original = billing.system_prompt
    before, after = _changed(
        monkeypatch, billing, "system_prompt", lambda name="": original(name) + "!"
    )
    assert before["billing"] != after["billing"]
    assert before["family_chat"] == after["family_chat"]


@pytest.mark.parametrize("name", ["CHAT_SYSTEM", "SUGGEST_SYSTEM", "MEMBER_RULE"])
def test_a_schedule_prompt_constant_change_is_seen(monkeypatch, name):
    from app.features.schedule.agent import prompts

    before, after = _changed(monkeypatch, prompts, name, getattr(prompts, name) + " 바뀜")
    assert before["schedule"] != after["schedule"]
    assert before["main"] == after["main"]


def test_a_schedule_schema_change_is_seen(monkeypatch):
    from app.features.schedule.agent import prompts

    before, after = _changed(monkeypatch, prompts, "CHAT_SCHEMA", {**prompts.CHAT_SCHEMA, "x": 1})
    assert before["schedule"] != after["schedule"]


def test_a_main_prompt_change_is_seen(monkeypatch):
    from app.features.ai_assistant import agents

    before, after = _changed(monkeypatch, agents, "PROMPT_NOTE", agents.PROMPT_NOTE + " 바뀜")
    assert before["main"] != after["main"]
    assert agent_hashes.integrated_hash(before) != agent_hashes.integrated_hash(after)
