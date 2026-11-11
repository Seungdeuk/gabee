"""단계 상한 관찰 시험(L0, LLM·DB 없음): `step_limit_reached`(상한에 닿음)와 `forced_final`(상한 때문에 도구 없이 최종 답)을 구분한다.

운영 흐름(모델 호출·도구 호출·답)은 바뀌지 않고 관찰만 정확해졌는지 본다. 단계 상한에 닿았다는 사실만으로 사례를 실패시키지 않는다."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from app.shared.llm import eval_hook, tool_graph
from evals.agent_eval.metrics import summarize
from evals.agent_eval.schema import Observation
from evals.agent_eval.store import read_trajectories
from tests.agent_eval.test_metrics import _case, _run
from tests.agent_eval.test_scoring import _call, _score
from tests.agent_eval.test_scoring import _case as scoring_case


class Scripted:
    """Run.model 대용: 정해 둔 답을 차례로 돌려주고 호출마다 받은 옵션(no_tools 등)을 남긴다."""

    def __init__(self, *replies):
        self.replies, self.kwargs = list(replies), []

    def invoke(self, _messages, **kwargs):
        self.kwargs.append(kwargs)
        return self.replies.pop(0)


def _tool(cid="t1", name="lookup"):
    return AIMessage(content="", tool_calls=[{"id": cid, "name": name, "args": {"q": "x"}}])


def _text(text="답", stop=None):
    return AIMessage(content=text, response_metadata={"stop_reason": stop} if stop else {})


def _round(calls):
    return tool_graph.ToolRound([(c["id"], "결과", False) for c in calls])


def _go(replies, max_steps, stage="main", handle=_round):
    model = Scripted(*replies)
    run = tool_graph.Run(model=model, handle=handle, max_steps=max_steps, stage=stage)
    with eval_hook.recording() as rec:
        tool_graph.run_graph(run, [HumanMessage("질문")])
    return run, rec, model


# 1. 상한 때문에 도구 없는 마지막 호출을 한 경우: 도달 O, 강제 최종 답 O
def test_forced_final_is_set_only_when_the_limit_forced_a_tool_less_last_call():
    run, rec, model = _go([_tool(), _text("최종")], max_steps=2)
    assert model.kwargs == [{}, {"no_tools": True}]  # 마지막 호출만 도구 없이
    assert run.forced_final and run.finished and run.answer == "최종"
    assert (rec.step_limit_reached, rec.forced_final) == (True, True)
    # 일반적인 도구 없는 답변은 강제 최종 답이 아니다
    run, rec, model = _go([_text("바로 답")], max_steps=3)
    assert not run.forced_final and model.kwargs == [{}]
    assert (rec.step_limit_reached, rec.forced_final) == (False, False)


# 2. 마지막 단계에서 정상적으로 답한 경우는 상한에 닿은 것이 아니다
def test_a_normal_answer_on_the_last_step_is_not_a_step_limit():
    run, rec, _ = _go([_text("바로 답")], max_steps=1)  # 첫 호출이 곧 마지막 단계
    assert run.finished and (rec.step_limit_reached, rec.forced_final) == (False, False)
    # 서버 도구 대기(pause_turn) 뒤 마지막 단계에서 정상 답: 앞 응답이 도구 결과가 아니라 강제 최종 답이 아니다
    run, rec, model = _go([_text("찾는 중", stop="pause_turn"), _text("끝")], max_steps=2)
    assert run.answer == "끝" and model.kwargs == [{}, {}] and not run.forced_final
    assert (rec.step_limit_reached, rec.forced_final) == (False, False)


# 3. 한 단계뿐인데 도구를 불러 답 없이 끊김: 도달 O, 강제 최종 답 X
def test_a_tool_call_on_the_only_step_is_a_limit_without_a_forced_final():
    run, rec, model = _go([_tool()], max_steps=1)
    assert not run.finished and not run.forced_final and model.kwargs == [{}]
    assert (rec.step_limit_reached, rec.forced_final) == (True, False)


# 4. pause_turn: 상한에서 대기로 끝나면 도달 O(강제 X), 상한 전에 이어서 답하면 도달 X
def test_pause_turn_is_a_limit_only_when_the_loop_ends_on_the_pause():
    run, rec, _ = _go(
        [_text("찾는 중", stop="pause_turn"), _text("또 찾는 중", stop="pause_turn")], max_steps=2
    )
    assert run.answer == "또 찾는 중" and not run.forced_final
    assert (rec.step_limit_reached, rec.forced_final) == (True, False)
    run, rec, _ = _go(
        [_text("찾는 중", stop="pause_turn"), _text("끝")], max_steps=4
    )  # 상한 전에 이어 받음
    assert (rec.step_limit_reached, rec.forced_final) == (False, False)


# 5. 중첩 Agent: 단계(stage)마다 따로 기록되어 서로 섞이지 않는다
def test_nested_agents_are_recorded_per_stage():
    def with_inner(inner_replies, inner_max):
        def handle(calls):
            inner = tool_graph.Run(
                model=Scripted(*inner_replies), handle=_round, max_steps=inner_max, stage="billing"
            )
            tool_graph.run_graph(inner, [HumanMessage("안쪽")])
            return _round(calls)

        return handle

    # 바깥(main)만 상한에 닿고 안쪽(billing)은 정상 답
    _, rec, _ = _go(
        [_tool("m1", "ask_billing"), _text("최종")], 2, handle=with_inner([_text("합계")], 4)
    )
    assert rec.stage_limits == {
        "billing": {"reached": False, "forced_final": False},
        "main": {"reached": True, "forced_final": True},
    }
    # 안쪽만 상한에 닿고 바깥은 정상 답
    _, rec, _ = _go(
        [_tool("m1", "ask_billing"), _text("끝")],
        4,
        handle=with_inner([_tool("b1", "get_month_summary"), _text("정리")], 2),
    )
    assert rec.stage_limits["billing"] == {"reached": True, "forced_final": True}
    assert rec.stage_limits["main"] == {"reached": False, "forced_final": False}
    assert (rec.step_limit_reached, rec.forced_final) == (True, True)  # 어느 단계든 있으면
    # 같은 단계가 여러 번 돌면 하나라도 닿았을 때 True 로 남는다
    with eval_hook.recording() as rec:
        eval_hook.observe_step_limit("billing", True, True)
        eval_hook.observe_step_limit("billing", False, False)
    assert rec.stage_limits["billing"] == {"reached": True, "forced_final": True}


# 6. 평가 훅이 꺼져 있으면 아무것도 계산·기록하지 않고 실행 결과는 같다
def test_nothing_is_computed_or_recorded_while_the_hook_is_off(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("훅이 꺼져 있는데 단계 상한을 계산했다")

    monkeypatch.setattr(tool_graph, "_step_limit_state", boom)
    results = []
    for _ in range(2):
        model = Scripted(_tool(), _text("최종"))
        run = tool_graph.Run(model=model, handle=_round, max_steps=2, stage="main")
        tool_graph.run_graph(run, [HumanMessage("질문")])
        results.append((run.answer, run.steps, run.finished, run.done, run.forced_final))
    assert eval_hook.current() is None and results[0] == results[1]
    monkeypatch.undo()
    with_hook = tool_graph.Run(
        model=Scripted(_tool(), _text("최종")), handle=_round, max_steps=2, stage="main"
    )
    with eval_hook.recording():
        tool_graph.run_graph(with_hook, [HumanMessage("질문")])
    assert (with_hook.answer, with_hook.steps, with_hook.finished, with_hook.done) == results[0][:4]
    # 단계 이름이 비어 있으면 켜져 있어도 기록하지 않는다
    _, rec, _ = _go([_tool(), _text("최종")], max_steps=2, stage="")
    assert rec.stage_limits == {} and not rec.step_limit_reached


# 7. 채점·지표: 도달·강제 최종 답만으로 실패시키지 않는다(실패한 사례의 원인으로만 센다)
def test_reaching_the_limit_never_fails_a_case_by_itself():
    case = scoring_case({"tools": {"required": ["register"]}})
    ok = _score(
        case,
        Observation(calls=[_call("register")], step_limit_reached=True, forced_final=True),
    )
    assert ok.passed and ok.failure_types == ()
    bad = _score(case, Observation(step_limit_reached=True, forced_final=True))
    assert not bad.passed and bad.failure_types == ("missing_tool", "step_limit")
    with pytest.raises(ValidationError):  # 강제 최종 답은 도달의 하위 사실이다
        Observation(forced_final=True)
    obs = [
        Observation(),
        Observation(step_limit_reached=True),
        Observation(step_limit_reached=True, forced_final=True),
        Observation(),
    ]
    e = summarize([_run(_case(str(i)), o) for i, o in enumerate(obs)]).efficiency
    assert (e.step_limit.k, e.forced_final.k, e.step_limit.n) == (2, 1, 4)


# ---- 하위 호환(옛 이름 step_limit_hit 로 저장된 결과를 읽고 집계해도 오류가 없다)
def test_old_observation_data_with_step_limit_hit_still_reads_and_scores():
    old = Observation.model_validate({"step_limit_hit": True, "steps": 3})
    assert old.step_limit_reached and not old.forced_final and old.step_limit_hit
    assert "step_limit_hit" not in old.model_dump()  # 저장은 새 이름으로만
    both = Observation.model_validate({"step_limit_hit": True, "step_limit_reached": False})
    assert not both.step_limit_reached  # 새 이름이 이긴다
    case = scoring_case({"tools": {"required": ["register"]}})
    assert _score(case, old).failure_types == ("missing_tool", "step_limit")  # 정책 그대로
    e = summarize([_run(_case("a"), old), _run(_case("b"), Observation())]).efficiency
    assert (e.step_limit.k, e.forced_final.k) == (1, 0)


def test_trajectories_stored_with_the_old_key_are_still_readable(tmp_path):
    (tmp_path / "trajectories.jsonl").write_text(
        json.dumps({"case_id": "a", "step_limit_hit": True}) + "\n"
        + json.dumps({"case_id": "b", "step_limit_reached": True, "forced_final": True}) + "\n"
        + json.dumps({"case_id": "c"}) + "\n\n",
        encoding="utf-8",
    )  # fmt: skip
    rows = {r["case_id"]: r for r in read_trajectories(tmp_path)}
    assert (rows["a"]["step_limit_reached"], rows["a"]["forced_final"]) == (True, False)
    assert "step_limit_hit" not in rows["a"]
    assert (rows["b"]["step_limit_reached"], rows["b"]["forced_final"]) == (True, True)
    assert (rows["c"]["step_limit_reached"], rows["c"]["forced_final"]) == (False, False)


def test_the_hook_fields_build_an_observation_and_the_old_property_name_still_works():
    with eval_hook.recording() as rec:
        eval_hook.observe_step_limit("main", True, True)
    obs = Observation(**rec.observation_fields())
    assert (obs.step_limit_reached, obs.forced_final) == (True, True)
    assert rec.step_limit_hit is True and obs.step_limit_hit is True  # 옛 이름(읽기 전용 별칭)
