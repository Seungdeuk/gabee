"""호출 추적(`call_trace`) 시험: 호출별 역할·stop_reason·max_tokens·도구 결과 상태가 기록되고, 본문·키·이름은 기록되지 않으며, 채점·비용은 그대로인지 본다.

실제 모델은 부르지 않는다(가짜 응답 딕셔너리와 가짜 모델 대본만 쓴다).
"""

import json

import pytest

from app.features.family_chat.ai_service import ANALYSIS_SYSTEM
from app.shared.llm.tool_graph import TRUNCATED_NOTE
from evals.agent_eval import call_trace, cli, dev_cases, dev_scripts, preflight, runner, usage
from evals.agent_eval import case_files as cf
from evals.agent_eval.call_trace import ASK_PREFIX, CallTracer
from tests.agent_eval.runner_support import run

CANARY_KEY = "sk-ant-canary-key-value-9999"
SECRET_NAME = "김비밀"
SECRET_PHONE = "010-9876-5432"


def reply(blocks, stop="end_turn", tokens=(100, 10), model="claude-haiku-5-5"):
    return {
        "id": "msg_x",
        "model": model,
        "content": blocks,
        "stop_reason": stop,
        "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]},
    }


def text(s):
    return {"type": "text", "text": s}


def tool_use(use_id, name, args=None):
    return {"type": "tool_use", "id": use_id, "name": name, "input": args or {}}


def body(system="당신은 가족 비서 '가비' 입니다", max_tokens=2048, messages=None, **extra):
    return {
        "model": "claude-haiku-5-5",
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages or [{"role": "user", "content": "질문"}],
        **extra,
    }


def results_body(*results, system="당신은 가족 비서 '가비' 입니다"):
    """앞 호출의 도구 결과가 실려 있는 요청 본문. results 는 (tool_use_id, content, is_error)."""
    blocks = [
        {"type": "tool_result", "tool_use_id": i, "content": c, "is_error": e}
        for i, c, e in results
    ]
    return body(
        system, messages=[{"role": "user", "content": "질문"}, {"role": "user", "content": blocks}]
    )


# ---------- 역할 ----------
@pytest.mark.parametrize(
    ("b", "role"),
    [
        (body(), "main"),
        (body("가계(정산) 담당 에이전트"), "billing"),
        (body("가족 채팅 담당 에이전트"), "family_chat"),
        (body(ANALYSIS_SYSTEM, output_config={"format": {}}), "analysis"),
        (body("일정 담당", output_config={"format": {}}), call_trace.OTHER_STRUCTURED),
        (
            body(ANALYSIS_SYSTEM),
            "main",
        ),  # 같은 프롬프트라도 구조화 출력이 아니면 분석 호출이 아니다
    ],
)
def test_role_is_read_from_the_request_body(b, role):
    assert call_trace.role_of(b) == role


def test_the_role_rule_agrees_with_the_preflight_rule_for_the_analysis_call():
    b = body(ANALYSIS_SYSTEM, output_config={"format": {}})
    assert preflight._is_analysis_body(b) and call_trace.role_of(b) == "analysis"


# ---------- stop_reason / max_tokens / 블록 ----------
def test_each_call_records_stop_reason_the_requested_max_tokens_and_token_counts():
    t = CallTracer("c1", 0)
    t.observe(body(max_tokens=1024), reply([text("답")], stop="max_tokens", tokens=(3486, 1024)))
    row = t.rows[0]
    assert (row["call_index"], row["role"], row["ok"]) == (0, "main", True)
    assert (row["max_tokens"], row["stop_reason"]) == (1024, "max_tokens")
    assert (row["tokens_in"], row["tokens_out"]) == (3486, 1024)
    assert row["output_blocks"] == {"text": 1} and row["text_chars"] == 1


def test_a_reply_without_any_text_block_is_visible_as_zero_text_chars():
    t = CallTracer("c1", 0)
    t.observe(body(max_tokens=1024), reply([{"type": "thinking", "thinking": "..."}], "max_tokens"))
    row = t.rows[0]
    assert row["text_chars"] == 0 and row["output_blocks"] == {"thinking": 1}
    assert call_trace.summarize(t.rows)["calls_without_text"] == 1
    assert call_trace.summarize(t.rows)["max_tokens_hits"] == 1


def test_requested_tools_and_call_order_are_kept():
    t = CallTracer("c1", 2)
    t.observe(
        body(),
        reply([tool_use("a", "analyze_recent_chat"), tool_use("b", "list_todos")], "tool_use"),
    )
    t.observe(body(), reply([text("끝")]))
    assert t.rows[0]["requested_tools"] == ["analyze_recent_chat", "list_todos"]
    assert [r["call_index"] for r in t.rows] == [0, 1] and t.rows[0]["repeat"] == 2


def test_the_summary_counts_only_empty_replies_not_tool_only_calls_or_failures():
    t = CallTracer("c1", 0)
    t.observe(body(), reply([tool_use("a", "list_todos")], "tool_use"))  # 도구만 요청한 정상 호출
    t.observe(body(), reply([text("끝")]))  # 글이 있는 호출
    t.observe(body(), reply([], "max_tokens"))  # 글도 도구 요청도 없는 응답
    t.observe(body(), None, ConnectionError("x"))  # 전송 실패
    s = call_trace.summarize(t.rows)
    assert s["calls_without_text"] == 1 and s["calls_failed"] == 1 and s["calls"] == 4
    assert s["stop_reasons"] == {
        "end_turn": 1,
        "max_tokens": 1,
        "tool_use": 1,
    }  # 실패 호출은 빠진다
    assert s["max_tokens_hits"] == 1


# ---------- 도구 결과 상태 / can_answer / fallback ----------
def ask_content(answer, can_answer):
    return json.dumps({"answer": answer, "can_answer": can_answer}, ensure_ascii=False)


def test_tool_results_record_name_error_flag_and_length_but_not_the_content():
    t = CallTracer("c1", 0)
    t.observe(body(), reply([tool_use("u1", "list_todos")], "tool_use"))
    t.observe(results_body(("u1", "x" * 321, False)), reply([text("끝")]))
    assert t.rows[1]["tool_results"] == [{"tool": "list_todos", "is_error": False, "chars": 321}]


def test_a_tool_error_is_recorded_as_an_error():
    t = CallTracer("c1", 0)
    t.observe(body(), reply([tool_use("u1", "search_messages")], "tool_use"))
    t.observe(results_body(("u1", '{"error": "x"}', True)), reply([text("끝")]))
    entry = t.rows[1]["tool_results"][0]
    assert entry["is_error"] is True and call_trace.summarize(t.rows)["tool_result_errors"] == 1


def test_ask_results_record_can_answer_and_the_fixed_failure_reason():
    t = CallTracer("c1", 0)
    t.observe(body(), reply([tool_use("u1", "ask_family_chat")], "tool_use"))
    failed = ask_content(f"{ASK_PREFIX}AI 응답이 비어 있어요", False)
    t.observe(results_body(("u1", failed, False)), reply([text("끝")]))
    entry = t.rows[1]["tool_results"][0]
    assert entry["tool"] == "ask_family_chat" and entry["can_answer"] is False
    assert entry["fallback_reason"] == "AI 응답이 비어 있어요" and entry["truncated_note"] is False
    assert call_trace.summarize(t.rows)["ask_results_cannot_answer"] == 1


def test_a_successful_ask_result_records_can_answer_true_and_the_truncation_note():
    t = CallTracer("c1", 0)
    t.observe(body(), reply([tool_use("u1", "ask_family_chat")], "tool_use"))
    t.observe(
        results_body(("u1", ask_content("답입니다" + TRUNCATED_NOTE, True), False)),
        reply([text("끝")]),
    )
    entry = t.rows[1]["tool_results"][0]
    assert entry["can_answer"] is True and entry["truncated_note"] is True
    assert "fallback_reason" not in entry and entry["answer_chars"] > 0


def test_an_unknown_failure_text_is_never_copied():
    """고정 머리말이 아닌 글(가족 이야기가 섞였을 수 있는 글)은 사유로 남기지 않는다."""
    t = CallTracer("c1", 0)
    t.observe(body(), reply([tool_use("u1", "ask_billing")], "tool_use"))
    t.observe(
        results_body(
            ("u1", ask_content(f"{SECRET_NAME} 이 {SECRET_PHONE} 로 보냈어요", False), False)
        ),
        reply([text("끝")]),
    )
    entry = t.rows[1]["tool_results"][0]
    assert entry["fallback_reason"] is None
    assert SECRET_NAME not in json.dumps(t.rows, ensure_ascii=False)


def test_a_result_is_recorded_once_even_though_later_bodies_repeat_it():
    t = CallTracer("c1", 0)
    t.observe(body(), reply([tool_use("u1", "list_todos")], "tool_use"))
    same = results_body(("u1", "{}", False))
    t.observe(same, reply([tool_use("u2", "list_todos")], "tool_use"))
    t.observe(results_body(("u1", "{}", False), ("u2", "{}", False)), reply([text("끝")]))
    assert (
        len(t.rows[1].get("tool_results", [])) == 1 and len(t.rows[2].get("tool_results", [])) == 1
    )


def test_an_unknown_tool_use_id_gives_no_tool_name_instead_of_a_guess():
    t = CallTracer("c1", 0)
    t.observe(results_body(("never-seen", "{}", False)), reply([text("끝")]))
    assert t.rows[0]["tool_results"][0]["tool"] is None


def test_a_transport_error_is_recorded_without_the_message():
    t = CallTracer("c1", 0)
    t.observe(body(max_tokens=77), None, RuntimeError(f"키 {CANARY_KEY} 가 새면 안 된다"))
    row = t.rows[0]
    assert row["ok"] is False and row["error_type"] == "RuntimeError" and row["max_tokens"] == 77
    assert CANARY_KEY not in json.dumps(t.rows)


def test_observation_never_raises_and_marks_a_trace_error_instead():
    t = CallTracer("c1", 0)
    t.observe({"messages": 5}, reply([text("x")]))  # 모양이 이상한 본문
    t.observe(body(), "응답이 객체가 아니다")
    assert t.rows[1]["ok"] is False
    assert all(isinstance(r, dict) for r in t.rows)


# ---------- 개인정보·키 ----------
def test_nothing_from_the_request_or_reply_content_is_stored():
    t = CallTracer("c1", 0)
    messages = [
        {"role": "user", "content": f"{SECRET_NAME} 전화는 {SECRET_PHONE}, 키는 {CANARY_KEY}"},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "u1",
                    "content": f"{SECRET_NAME} {SECRET_PHONE}",
                    "is_error": False,
                }
            ],
        },
    ]
    t.observe(
        body(messages=messages, system=f"SYSMARK_QX {CANARY_KEY}"),
        reply([tool_use("u1", "list_todos", {"q": SECRET_NAME}), text(f"답 {SECRET_PHONE}")]),
    )
    dump = json.dumps(call_trace.report(t.rows), ensure_ascii=False)
    for secret in (SECRET_NAME, SECRET_PHONE, CANARY_KEY, "SYSMARK_QX"):
        assert secret not in dump


def test_the_report_lists_only_known_keys():
    t = CallTracer("c1", 0)
    t.observe(body(), reply([tool_use("u1", "ask_family_chat")], "tool_use"))
    t.observe(results_body(("u1", ask_content("답", True), False)), reply([text("끝")]))
    allowed = {
        "case_id", "repeat", "call_index", "role", "model", "max_tokens", "ok", "tool_results",
        "error_type", "stop_reason", "tokens_in", "tokens_out", "output_blocks", "text_chars",
        "requested_tools", "trace_error",
    }  # fmt: skip
    for row in t.rows:
        assert set(row) <= allowed
        for r in row.get("tool_results", []):
            assert set(r) <= {
                "tool", "is_error", "chars", "can_answer", "answer_chars", "truncated_note",
                "fallback_reason",
            }  # fmt: skip


# ---------- 측정기 연결: 동작은 그대로 ----------
def test_the_meter_traces_calls_and_keeps_counts_identical_with_and_without_a_tracer(monkeypatch):
    from app.shared.llm import transport

    def fake_post(b, **k):
        return reply([text("끝")], tokens=(11, 7))

    monkeypatch.setattr(transport, "post_messages", fake_post)
    with usage.meter_llm_calls() as plain:
        transport.post_messages(body())
    tracer = CallTracer("c", 0)
    with usage.meter_llm_calls(tracer=tracer) as traced:
        out = transport.post_messages(body())
    assert out == reply([text("끝")], tokens=(11, 7))
    assert (traced.tokens_in, traced.tokens_out, len(traced.calls)) == (
        plain.tokens_in,
        plain.tokens_out,
        len(plain.calls),
    )
    assert len(tracer.rows) == 1 and tracer.rows[0]["tokens_in"] == 11
    assert transport.post_messages is fake_post  # 끝나면 원래 함수로 돌아온다


def test_a_broken_tracer_cannot_change_the_call_result(monkeypatch):
    from app.shared.llm import transport

    class Broken:
        def observe(self, *a, **k):
            raise RuntimeError("추적기 오류")

    monkeypatch.setattr(transport, "post_messages", lambda b, **k: reply([text("끝")]))
    with usage.meter_llm_calls(tracer=Broken()) as meter:
        out = transport.post_messages(body())
    assert out["stop_reason"] == "end_turn" and len(meter.calls) == 1


def test_a_transport_failure_is_traced_and_still_raised(monkeypatch):
    from app.shared.llm import transport

    def boom(b, **k):
        raise ConnectionError("끊김")

    monkeypatch.setattr(transport, "post_messages", boom)
    tracer = CallTracer("c", 0)
    with usage.meter_llm_calls(tracer=tracer) as meter:
        with pytest.raises(ConnectionError):
            transport.post_messages(body())
    assert tracer.rows[0]["error_type"] == "ConnectionError" and meter.calls[0].ok is False


# ---------- 실행기: chat-03 가짜 실행 ----------
@pytest.fixture(scope="module")
def chat03():
    return [c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev") if c.id == "s-dev-05-chat-03"]


@pytest.fixture(scope="module")
def runs(chat03, tmp_path_factory):
    scripts = dev_scripts.scripts_for("dev")
    root = tmp_path_factory.mktemp("diag")
    off = run(chat03, root / "off", run_id="diag-off", scripts=scripts)
    on = run(chat03, root / "on", run_id="diag-on", scripts=scripts, diagnostics=True)
    return off, on, root


def test_the_diagnostics_file_is_written_only_when_asked(runs):
    off, on, _ = runs
    assert not (off.run_dir / runner.DIAGNOSTICS_FILE).exists()
    assert (on.run_dir / runner.DIAGNOSTICS_FILE).exists()
    assert not off.call_traces and on.call_traces


def test_chat_03_records_each_call_with_role_stop_reason_max_tokens_and_tool_results(runs):
    """가짜 대본의 정상 경로: 소통 Agent 가 답하면 메인은 그 답을 그대로 돌려줘서(직통 답) 메인의 두 번째 호출이 없다."""
    _, on, _ = runs
    doc = json.loads((on.run_dir / runner.DIAGNOSTICS_FILE).read_text("utf-8"))
    rows = doc["calls"]
    assert [r["role"] for r in rows] == ["main", "family_chat", "analysis", "family_chat"]
    assert [r["call_index"] for r in rows] == [0, 1, 2, 3]
    assert all(r["ok"] and r["stop_reason"] for r in rows)
    assert rows[2]["max_tokens"] == 3000 and rows[3]["max_tokens"] == 1024
    assert rows[1]["requested_tools"] == ["analyze_recent_chat", "list_todos"]
    names = [t["tool"] for r in rows for t in r.get("tool_results", [])]
    assert names == ["analyze_recent_chat", "list_todos"]
    # 한계: 메인이 두 번째로 부르지 않으면 `ask_family_chat` 결과가 실린 요청이 없어 그 결과의 can_answer 는 기록에 없다
    assert doc["summary"]["calls"] == 4 and doc["summary"]["calls_by_role"]["analysis"] == 1


def test_a_failing_family_chat_agent_shows_can_answer_false_and_the_reason_in_the_main_call(
    chat03, tmp_path
):
    """소통 Agent 가 모델 호출에 실패하면 메인은 can_answer=false 결과를 받아 한 번 더 부른다. 그 결과의 상태가 기록된다(chat-03 실호출에서 확인하려는 것)."""
    from evals.agent_eval.fake_model import call, say

    script = {
        "s-dev-05-chat-03": {
            "main": [
                call("ask_family_chat", {"question": "최근 대화를 정리해 줘"}),
                say("지금은 확인하지 못했어요"),
            ]
        }  # family_chat 대본이 없어 그 Agent 의 모델 호출이 실패한다
    }
    report = run(chat03, tmp_path, run_id="diag-cf", scripts=script, diagnostics=True)
    rows = report.call_traces
    assert [r["role"] for r in rows if r["ok"]] == ["main", "main"]
    failed = [r for r in rows if not r["ok"]]
    assert (
        failed
        and failed[0]["role"] == "family_chat"
        and failed[0]["error_type"] == "ScriptExhausted"
    )
    ask = rows[-1]["tool_results"][0]
    assert (
        ask["tool"] == "ask_family_chat" and ask["can_answer"] is False and ask["is_error"] is False
    )
    assert ask["fallback_reason"] == "AI 호출에 실패했어요 (ScriptExhausted)"
    doc = call_trace.summarize(rows)
    assert doc["ask_results_cannot_answer"] == 1 and doc["calls_by_role"]["family_chat"] == 1


def test_diagnostics_do_not_change_judgement_cost_or_stored_results(runs):
    off, on, root = runs
    a, b = off.records[0].as_dict(), on.records[0].as_dict()
    assert a == b
    assert off.ledger.total == on.ledger.total and len(off.ledger.usages) == len(on.ledger.usages)
    assert [u.as_dict() for u in off.ledger.usages] == [u.as_dict() for u in on.ledger.usages]
    obs_off, obs_on = (
        off.observations[("s-dev-05-chat-03", 0)],
        on.observations[("s-dev-05-chat-03", 0)],
    )
    assert obs_off.model_dump() == obs_on.model_dump()
    for name in ("cases.jsonl", "trajectories.jsonl", "usage.jsonl", "summary.csv", "failures.csv"):
        assert (off.run_dir / name).read_bytes() == (on.run_dir / name).read_bytes()


def test_the_trace_matches_the_usage_rows_call_for_call(runs):
    _, on, _ = runs
    rows = on.call_traces
    usages = [u.as_dict() for u in on.ledger.usages]
    assert len(rows) == len(usages) == 4
    assert [r["tokens_in"] for r in rows] == [u["tokens_in"] for u in usages]
    assert [r["tokens_out"] for r in rows] == [u["tokens_out"] for u in usages]


def test_the_stored_diagnostics_contain_no_question_answer_or_arguments(runs, chat03):
    _, on, _ = runs
    dump = (on.run_dir / runner.DIAGNOSTICS_FILE).read_text("utf-8")
    assert chat03[0].question not in dump and "@가비" not in dump
    for needle in preflight._needles_of(chat03[0])[0]:
        assert needle not in dump


def test_a_failing_model_call_is_still_traced(tmp_path):
    cases = [
        c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev") if c.id == "s-dev-12-toolfail-02"
    ]
    report = run(
        cases,
        tmp_path,
        run_id="diag-fail",
        scripts=dev_scripts.scripts_for("dev"),
        diagnostics=True,
    )
    assert report.call_traces
    failed = [r for r in report.call_traces if not r["ok"]]
    assert failed and all("error_type" in r for r in failed)


def test_the_default_results_folder_is_git_ignored_so_the_file_is_not_tracked():
    ignored, _ = preflight._git_ignored(cli.DEFAULT_RESULTS / "x" / runner.DIAGNOSTICS_FILE)
    assert ignored is True


def test_the_cli_flag_reaches_the_run_options():
    args = cli.build_parser().parse_args(["--fake", "--call-diagnostics"])
    assert args.call_diagnostics is True
    assert cli.build_parser().parse_args(["--fake"]).call_diagnostics is False
