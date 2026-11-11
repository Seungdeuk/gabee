"""모델 호출 측정기 시험(L0). 가짜 응답을 `transport.post_messages` 자리에 끼우고 실제 네트워크·모델은 쓰지 않는다."""

import json
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import select

from app.features.billing import agent as billing_agent
from app.features.family_group.models import User
from app.features.schedule.agent import handler
from app.features.schedule.agent.schemas import AgentRequest
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from app.shared.llm import eval_hook, transport
from evals.agent_eval.cost import Ledger, Scope, call_cost
from evals.agent_eval.usage import RunHalted, meter_llm_calls

MODEL = "claude-haiku-5-5"


def _usage(i=100, o=20):
    return {"input_tokens": i, "output_tokens": o}


def _json_payload(data, i=100, o=20, model=MODEL):
    return {
        "content": [{"type": "text", "text": json.dumps(data)}],
        "usage": _usage(i, o),
        "model": model,
    }


def _install(monkeypatch, *payloads, repeat_last=False):
    queue = iter(payloads)
    calls = []
    last = {}

    def fake(body, **kwargs):
        calls.append(body)
        try:
            last["v"] = next(queue)
        except StopIteration:
            if not repeat_last:
                raise
        if isinstance(last["v"], Exception):
            raise last["v"]
        return last["v"]

    monkeypatch.setattr(transport, "post_messages", fake)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    return calls


@pytest.fixture
def me(client, family):
    a, _, group = family
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.name == "지민")).first()
    return user, group["id"]


def test_the_schedule_classification_call_is_counted_without_touching_app_code(me, monkeypatch):
    user, gid = me
    data = {
        "intent": "register",
        "reply": "",
        "event_ids": [],
        "register": {"title": "치과", "date": "2099-01-01"},
    }
    _install(monkeypatch, _json_payload(data, 321, 45))
    with meter_llm_calls() as meter, SessionLocal() as db:
        handler.handle(
            db, user.id, gid, AgentRequest(text="치과 등록", channel="personal"), guarded=False
        )
    assert [(c.model, c.tokens_in, c.tokens_out, c.ok) for c in meter.calls] == [
        (MODEL, 321, 45, True)
    ]


def test_tool_loop_calls_are_counted_and_agree_with_the_hook(me, monkeypatch):
    user, gid = me
    tool = {
        "content": [
            {
                "type": "tool_use",
                "id": "t1",
                "name": "get_month_summary",
                "input": {"month": "2026-10"},
            }
        ],
        "usage": _usage(50, 10),
        "model": MODEL,
    }
    done = {"content": [{"type": "text", "text": "합계"}], "usage": _usage(70, 5), "model": MODEL}
    _install(monkeypatch, tool, done)
    with eval_hook.recording() as rec, meter_llm_calls() as meter, SessionLocal() as db:
        billing_agent.ask(
            db, gid, user, "얼마 썼어?", guarded=False
        )  # post 를 주지 않아 transport 를 지난다
    assert [(c.tokens_in, c.tokens_out) for c in meter.calls] == [(50, 10), (70, 5)]
    assert (meter.tokens_in, meter.tokens_out) == (rec.tokens_in, rec.tokens_out) == (120, 15)
    assert len(meter.calls) == rec.llm_calls == 2


def test_a_failed_call_is_recorded_with_zero_tokens_and_the_error_still_propagates(monkeypatch):
    _install(monkeypatch, httpx.ConnectError("끊김"))
    with meter_llm_calls() as meter, pytest.raises(httpx.ConnectError):
        transport.post_messages({"model": MODEL, "max_tokens": 10})
    assert [(c.tokens_in, c.tokens_out, c.ok) for c in meter.calls] == [(0, 0, False)]


def test_calls_are_added_to_the_ledger_as_they_finish_so_spending_accumulates_within_a_case(
    monkeypatch,
):
    """한 사례의 여러 호출(메인·하위 Agent·일정 분류)이 호출마다 누적되어 상한을 지킨다."""
    calls = _install(monkeypatch, _json_payload({}, 200_000, 4_000), repeat_last=True)
    cap = D("0.01")
    ledger = Ledger((Scope.RUN,), caps={Scope.RUN: cap})
    one_call = call_cost(MODEL, 200_000, 4_000)
    body = {"model": MODEL, "max_tokens": 4_000, "messages": [{"role": "user", "content": "안녕"}]}
    with meter_llm_calls(ledger, "c1", 0) as meter, pytest.raises(RunHalted):
        for _ in range(10):
            transport.post_messages(body)
    assert len(calls) == len(meter.calls) < 10  # 열 번을 다 부르지 못한다
    assert ledger.total <= cap + one_call  # 넘어도 호출 하나 몫이 최대다
    assert ledger.total == sum((u.cost for u in ledger.usages), D(0))


def test_the_guard_stops_a_call_that_could_exceed_the_cap_before_it_is_made(monkeypatch):
    calls = _install(monkeypatch, _json_payload({}))
    tiny = Ledger((Scope.RUN,), caps={Scope.RUN: D("0.0003")})
    body = {"model": MODEL, "max_tokens": 4000, "messages": [{"role": "user", "content": "안녕"}]}
    with meter_llm_calls(tiny) as meter, pytest.raises(RunHalted, match="호출 전에"):
        transport.post_messages(body)
    assert calls == [] and meter.calls == []  # 실제 호출도 기록도 없다
    with meter_llm_calls(tiny) as meter:
        transport.post_messages({**body, "max_tokens": 1})  # 상한 안이면 통과한다
    assert len(meter.calls) == 1


def test_the_input_estimate_is_conservative_for_korean_text_and_includes_overhead(monkeypatch):
    korean = "가" * 1000
    calls = _install(monkeypatch, _json_payload({}))
    ledger = Ledger((Scope.RUN,))
    body = {"model": MODEL, "max_tokens": 1, "messages": [{"role": "user", "content": korean}]}
    with meter_llm_calls(ledger):
        transport.post_messages(body)
    from evals.agent_eval.usage import estimate_input_tokens

    assert (
        estimate_input_tokens(body) >= 2500 and len(calls) == 1
    )  # 한글 1000자(글자당 1토큰) + 숨은 프롬프트 1500


def test_an_unpriced_model_halts_the_run_instead_of_being_swallowed_as_a_fallback(monkeypatch):
    """앱은 ValueError 를 삼켜 규칙 기반 답으로 넘어가므로, 단가 없는 모델은 삼켜지지 않는 예외로 멈춘다."""
    _install(monkeypatch, _json_payload({}, model="mystery-model"))
    body = {"model": "mystery-model", "max_tokens": 10, "messages": []}
    with meter_llm_calls(Ledger((Scope.RUN,))), pytest.raises(RunHalted):
        try:
            transport.post_messages(body)
        except Exception:  # noqa: BLE001  앱의 넓은 except 처럼 삼키려 해도 통과하지 못한다
            pytest.fail("RunHalted 가 except Exception 에 걸렸다")


def test_run_halted_is_not_swallowed_by_the_client_json_call(me, monkeypatch):
    _install(monkeypatch, _json_payload({}, 100, 20))
    tiny = Ledger((Scope.RUN,), caps={Scope.RUN: D("0.00000001")})
    with meter_llm_calls(tiny), pytest.raises(RunHalted):
        llm.complete_json("p", {"type": "object"}, max_tokens=900)


def test_the_original_function_is_restored_even_after_an_error(monkeypatch):
    _install(monkeypatch, _json_payload({}))
    before = transport.post_messages
    with pytest.raises(ZeroDivisionError), meter_llm_calls():
        assert transport.post_messages is not before
        raise ZeroDivisionError
    assert transport.post_messages is before
