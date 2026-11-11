"""4개 Agent 가 `stage` 를 넘기는지, 평가가 꺼져 있으면 동작이 같은지 보는 시험(L0). 가짜 모델·합성 데이터만 쓴다."""

import pytest
from sqlalchemy import select

from app.features.ai_assistant.knowledge import rag_chat
from app.features.billing import agent as billing_agent
from app.features.family_chat import agent as chat_agent
from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import eval_hook
from app.shared.llm.agent import Tool, ask_agent
from tests.ai_consent import enable_ai_for_user


def _tool_use(name, args, id_="t1"):
    return {"content": [{"type": "tool_use", "id": id_, "name": name, "input": args}]}


def _text(text):
    return {"content": [{"type": "text", "text": text}]}


def _scripted(*replies):
    queue = iter(replies)
    return lambda body: next(queue)


def _by_agent(**scripts):
    """시스템 프롬프트로 어느 Agent 의 호출인지 가려 그 Agent 의 대본대로 답하는 가짜 모델."""
    queues = {k: iter(v) for k, v in scripts.items()}

    def post(body):
        system = body["system"]
        key = "billing" if "가계(정산) 담당" in system else "main"
        return next(queues[key])

    return post


@pytest.fixture
def me(client, family, monkeypatch):
    a, _, group = family
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    enable_ai_for_user()
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.name == "지민")).first()
    return user, group["id"]


def _billing(user, gid):
    def run(post):
        with SessionLocal() as db:
            r = billing_agent.ask(db, gid, user, "이번 달 얼마 썼어?", post=post, guarded=False)
        return r.answer, [c["name"] for c in r.tool_calls]

    return run, lambda: _scripted(
        _tool_use("get_month_summary", {"month": "2026-10"}), _text("합계")
    )


def _family_chat(user, gid):
    def run(post):
        with SessionLocal() as db:
            r = chat_agent.ask(db, gid, user, "할 일 알려줘", post=post, guarded=False)
        return r.answer, [c["name"] for c in r.tool_calls]

    return run, lambda: _scripted(_tool_use("list_todos", {}), _text("없어요"))


def _main(user, gid):
    def run(post):
        with SessionLocal() as db:
            r = rag_chat.ask(db, gid, "기록 알려줘", post=post, user=user)
        return r.answer, [c["name"] for c in r.tool_calls]

    return run, lambda: _scripted(_tool_use("list_items", {}), _text("기록이 없어요"))


@pytest.mark.parametrize(
    ("make", "stage", "tool"),
    [
        (_billing, "billing", "get_month_summary"),
        (_family_chat, "family_chat", "list_todos"),
        (_main, "main", "list_items"),
    ],
)
def test_each_agent_records_its_own_stage_and_behaves_the_same_without_recording(
    make, stage, tool, me
):
    user, gid = me
    run, script = make(user, gid)
    plain = run(script())  # 평가가 꺼져 있다
    assert eval_hook.current() is None
    with eval_hook.recording() as rec:
        observed = run(script())
    assert observed == plain  # 켜도 답과 도구 호출은 같다
    assert [(c["stage"], c["name"]) for c in rec.calls] == [(stage, tool)]
    assert rec.steps >= 1


def test_main_calling_a_tab_agent_records_both_stages(me):
    user, gid = me
    post = _by_agent(
        main=[_tool_use("ask_billing", {"question": "이번 달 얼마?"}), _text("정리했어요")],
        billing=[_tool_use("get_month_summary", {"month": "2026-10"}), _text("합계")],
    )
    with eval_hook.recording() as rec, SessionLocal() as db:
        rag_chat.ask(db, gid, "이번 달 지출 알려줘", post=post, user=user)
    # 메인의 도구 호출은 그 도구(하위 Agent)가 끝난 뒤에 기록되므로 안쪽 호출이 먼저 나온다
    assert [(c["stage"], c["name"]) for c in rec.calls] == [
        ("billing", "get_month_summary"),
        ("main", "ask_billing"),
    ]


def test_without_a_stage_nothing_is_recorded_so_existing_callers_are_unchanged():
    tool = Tool("echo", "d", {"type": "object", "properties": {}}, lambda a: {"ok": True})
    post = _scripted(_tool_use("echo", {}), _text("끝"))
    with eval_hook.recording() as rec:
        reply = ask_agent("system", "q", [tool], post=post)  # stage 를 주지 않은 기존 호출 방식
    assert reply.answer == "끝" and rec.calls == []
    post = _scripted(_tool_use("echo", {}), _text("끝"))
    with eval_hook.recording() as rec:
        ask_agent("system", "q", [tool], post=post, stage="billing")
    assert [c["stage"] for c in rec.calls] == ["billing"]
