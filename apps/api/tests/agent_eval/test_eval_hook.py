"""평가 전용 관찰 훅 시험(L0, LLM·DB 없음). 꺼져 있으면 동작이 같고, 켜면 인자·단계·오류·토큰이 기록되는지 본다."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.features.schedule.agent import chat
from app.shared.llm import eval_hook, tool_graph
from evals.agent_eval.schema import Case, Observation, Security
from evals.agent_eval.scoring import score_case


class ScriptedModel:
    """Run.model 대용: 정해 둔 답을 차례로 돌려준다(도구 호출·토큰 포함)."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.kwargs = []  # 호출마다 받은 옵션(no_tools 등)

    def invoke(self, _messages, **kwargs):
        self.kwargs.append(kwargs)
        return self.replies.pop(0)


def _tool_reply(*calls, usage=(10, 5)):
    return AIMessage(
        content="",
        tool_calls=[{"id": cid, "name": n, "args": a} for cid, n, a in calls],
        usage_metadata={
            "input_tokens": usage[0],
            "output_tokens": usage[1],
            "total_tokens": sum(usage),
        },
    )


def _final(text="끝", usage=(7, 3)):
    return AIMessage(
        content=text,
        usage_metadata={
            "input_tokens": usage[0],
            "output_tokens": usage[1],
            "total_tokens": sum(usage),
        },
    )


def _go(stage="", max_steps=4, fail=()):
    seen = []

    def handle(calls):
        seen.append([(c["id"], c["name"], c["args"]) for c in calls])
        return tool_graph.ToolRound(
            [(c["id"], "결과", c["id"] in fail) for c in calls],
        )

    model = ScriptedModel(
        _tool_reply(("a", "register", {"title": "치과", "when": {"date": "2026-11-12"}})),
        _tool_reply(("b", "lookup", {"q": "x"}), ("c", "lookup", {"q": "y"})),
        _final(),
    )
    run = tool_graph.Run(model=model, handle=handle, max_steps=max_steps, stage=stage)
    tool_graph.run_graph(run, [])
    return run, seen


def test_hook_is_off_by_default_and_changes_nothing():
    assert eval_hook.current() is None
    plain, seen_plain = _go(stage="main")  # 기록기가 없으면 단계를 넘겨도 아무 일도 없다
    with eval_hook.recording() as rec:
        recorded, seen_recorded = _go(stage="main")
    assert (plain.answer, plain.steps, plain.finished, plain.done) == (
        recorded.answer,
        recorded.steps,
        recorded.finished,
        recorded.done,
    )
    assert seen_plain == seen_recorded  # 도구에 넘어간 호출이 같다
    assert rec.calls  # 켠 쪽만 기록됐다
    assert eval_hook.current() is None  # 끝나면 다시 꺼진다


def test_empty_stage_records_nothing_even_when_recording():
    with eval_hook.recording() as rec:
        _go(stage="")
    assert rec.calls == [] and rec.steps == 0 and rec.tokens_in == 0


def test_records_calls_args_stage_errors_tokens_and_steps():
    with eval_hook.recording() as rec:
        run, _ = _go(stage="family_chat", fail={"c"})
    assert run.answer == "끝"
    assert [(c["stage"], c["name"], c["is_error"]) for c in rec.calls] == [
        ("family_chat", "register", False),
        ("family_chat", "lookup", False),
        ("family_chat", "lookup", True),
    ]
    assert rec.calls[0]["args"] == {"title": "치과", "when.date": "2026-11-12"}  # 중첩 인자를 편다
    assert (rec.steps, rec.llm_calls) == (3, 3)
    assert (rec.tokens_in, rec.tokens_out) == (10 + 10 + 7, 5 + 5 + 3)
    assert (rec.step_limit_reached, rec.forced_final) == (False, False)


def test_step_limit_is_recorded_when_the_loop_hit_the_limit():
    model = ScriptedModel(_tool_reply(("a", "lookup", {})), _final("최종"))
    run = tool_graph.Run(
        model=model,
        handle=lambda calls: tool_graph.ToolRound([(calls[0]["id"], "결과", False)]),
        max_steps=2,
        stage="main",
    )
    with eval_hook.recording() as rec:
        tool_graph.run_graph(run, [HumanMessage("질문")])
    assert run.finished and run.forced_final and model.kwargs == [{}, {"no_tools": True}]
    assert (rec.step_limit_reached, rec.forced_final) == (True, True)


def test_recording_copies_arguments_and_reports_observation_fields():
    args = {"title": "치과", "share_ids": ["m1"]}
    with eval_hook.recording() as rec:
        eval_hook.observe_call("schedule", "schedule.register", args)
        args["share_ids"].append("later")  # 기록 뒤에 바뀌어도 기록은 그대로다
        fields = rec.observation_fields()
    assert rec.calls[0]["args"]["share_ids"] == ["m1"]
    fields["calls"][0]["args"]["title"] = "바뀜"  # 꺼내 간 값을 바꿔도 기록은 그대로다
    assert rec.calls[0]["args"]["title"] == "치과"
    obs = Observation(**eval_hook.Recording(calls=rec.calls).observation_fields())
    assert obs.calls[0].name == "schedule.register" and obs.calls[0].stage == "schedule"


def test_mark_last_marks_the_latest_matching_call_only():
    with eval_hook.recording() as rec:
        eval_hook.observe_call("schedule", "schedule.register", {"title": "a"})
        eval_hook.observe_call("schedule", "schedule.register", {"title": "b"})
        assert eval_hook.mark_last("schedule.register", is_error=True) is True
        assert eval_hook.mark_last("schedule.register", superseded=True) is True
        assert eval_hook.mark_last("nothing", is_error=True) is False
    assert [(c["is_error"], c["superseded"]) for c in rec.calls] == [(False, False), (True, True)]
    assert eval_hook.mark_last("schedule.register", is_error=True) is False  # 꺼져 있으면 False


def test_recordings_do_not_leak_between_nested_or_sequential_uses():
    with eval_hook.recording() as outer:
        eval_hook.observe_call("main", "a", {})
        with eval_hook.recording() as inner:
            eval_hook.observe_call("main", "b", {})
        eval_hook.observe_call("main", "c", {})
    assert [c["name"] for c in outer.calls] == ["a", "c"]
    assert [c["name"] for c in inner.calls] == ["b"]


def test_wrong_arguments_fail_the_scorer_end_to_end():
    case = Case.model_validate(
        {
            "id": "hook-1",
            "split": "dev",
            "category": "C",
            "scenario": "single_tool",
            "agent_path": "main",
            "question": "내일 3시 치과 등록해줘",
            "expect": {
                "tools": {"required": ["register"]},
                "calls": [
                    {"tool": "register", "args": [{"arg": "title", "match": "eq", "value": "치과"}]}
                ],
            },
            "meta": {"synthetic": True},
        }
    )

    def observe(title):
        model = ScriptedModel(_tool_reply(("a", "register", {"title": title})), _final())
        run = tool_graph.Run(
            model=model,
            handle=lambda calls: tool_graph.ToolRound([(c["id"], "ok", False) for c in calls]),
            max_steps=3,
            stage="main",
        )
        with eval_hook.recording() as rec:
            tool_graph.run_graph(run, [])
        return Observation(answer=run.answer, **rec.observation_fields())

    assert score_case(case, observe("치과"), Security()).passed
    wrong = score_case(case, observe("미용실"), Security())
    assert not wrong.passed and "arg_error" in wrong.failure_types


def _cleaned(intent, **kw):
    base = {
        "intent": intent,
        "reply": "",
        "event_ids": [],
        "period_start": "",
        "period_end": "",
        "keyword": "",
        "register": {},
        "target_id": "",
        "changes": {},
        "check_action": "",
        "request": {},
        "habit": {},
    }
    return {**base, **kw}


def test_schedule_structured_output_becomes_a_named_call():
    with eval_hook.recording() as rec:
        chat._observe(_cleaned("register", register={"title": "치과", "date": "2026-11-12"}))
        chat._observe(_cleaned("edit", target_id="e1", changes={"title": "미용실"}))
        chat._observe(_cleaned("query", period_start="2026-11-01", keyword="치과"))
        chat._observe(_cleaned("not_schedule"))
    assert [(c["stage"], c["name"]) for c in rec.calls] == [
        ("schedule", "schedule.register"),
        ("schedule", "schedule.edit"),
        ("schedule", "schedule.query"),
    ]
    assert rec.calls[0]["args"]["title"] == "치과"
    assert rec.calls[1]["args"] == {"target_id": "e1", "title": "미용실"}
    assert rec.calls[2]["args"]["keyword"] == "치과"
    chat._observe(_cleaned("register"))  # 꺼져 있으면 기록기가 없어 아무 일도 없다


@pytest.fixture
def fake_llm(monkeypatch):
    payload = {
        "intent": "register",
        "reply": "등록할게요",
        "register": {
            "title": "치과",
            "date": "2026-11-12",
            "start_time": "15:00",
            "end_time": "",
            "kind": 1,
        },
    }
    response = SimpleNamespace(data=payload, calls=1, input_tokens=1, output_tokens=1)
    monkeypatch.setattr(chat.llm, "complete_json", lambda *a, **k: response)
    monkeypatch.setattr(chat.ai_guard, "count_nested", lambda *a, **k: None)
    return payload


def _converse(**kw):
    return chat.converse(
        None, "u1", "g1", "내일 3시 치과 등록해줘", datetime(2026, 11, 11, 9, 0),
        [], 0, None, set(), guarded=False, **kw,
    )  # fmt: skip


def test_converse_result_is_the_same_with_and_without_recording(fake_llm):
    plain = _converse()
    with eval_hook.recording() as rec:
        recorded = _converse()
    assert recorded == plain  # 켜도 돌려주는 값이 같다
    assert [c["name"] for c in rec.calls] == ["schedule.register"]
    assert rec.calls[0]["args"]["title"] == "치과"


def test_a_second_classification_of_the_same_question_supersedes_the_first():
    with eval_hook.recording() as rec:
        chat._observe(_cleaned("delete", target_id="e1"))
        chat._observe(_cleaned("delete", target_id="e1"))  # need_wider 로 다시 분류
    assert [c["superseded"] for c in rec.calls] == [True, False]


def test_a_malformed_tool_call_is_skipped_and_the_rest_are_still_recorded():
    with eval_hook.recording() as rec:
        eval_hook.observe_tools(
            "main",
            [
                {"id": "x"},
                {"id": "y", "name": "lookup", "args": {"q": 1}},
            ],  # 앞의 것은 name 이 없다
            [("y", "ok", True)],
        )
    assert [(c["name"], c["is_error"]) for c in rec.calls] == [("lookup", True)]
    eval_hook.observe_model("main", object())  # 토큰 정보가 없어도 예외 없이 지나간다


def test_nothing_is_recorded_anywhere_while_off():
    _go(stage="main")
    assert eval_hook.current() is None
    with eval_hook.recording() as fresh:  # 꺼져 있을 때의 호출이 새 기록에 새어 들어오지 않는다
        pass
    assert fresh.calls == [] and fresh.steps == 0 and fresh.tokens_in == 0


def test_step_limit_is_not_flagged_when_the_model_answers_directly():
    model = ScriptedModel(_final())
    run = tool_graph.Run(
        model=model, handle=lambda calls: tool_graph.ToolRound([]), max_steps=1, stage="main"
    )
    with eval_hook.recording() as rec:
        tool_graph.run_graph(run, [HumanMessage("질문")])
    assert run.finished and (rec.step_limit_reached, rec.forced_final) == (False, False)
