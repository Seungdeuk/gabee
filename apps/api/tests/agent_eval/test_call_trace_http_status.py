"""호출 추적(`call_trace`)의 HTTP 오류 진단 시험(L0·L2, 실제 Claude 호출 없음).

호출이 HTTP 오류 응답(`httpx.HTTPStatusError`)으로 끝나면 상태 코드(`http_status`)와 응답 JSON 의 `error.type` 중 허용 목록에 있는 값(`api_error_type`)만 남긴다.
키·요청/응답 본문·질문·도구 인자·예외 메시지·요청 주소·응답 헤더는 저장하지 않고, 연결 오류·시간 초과는 예전처럼 예외 종류만 남긴다.
"""

import json
from decimal import Decimal

import httpx
import pytest

from app.shared.llm import transport
from evals.agent_eval import call_trace, cli, preflight, real_gate, runner, usage
from evals.agent_eval.call_trace import ASK_PREFIX, CallTracer
from tests.agent_eval.test_call_trace import ask_content, body, reply, results_body, text, tool_use

CANARY_KEY = "sk-ant-canary-key-value-9999"
CANARY_MSG = "CANARY_MESSAGE_가나다_x-api-key invalid"
CANARY_USER = "CANARY_QUESTION 김비밀 010-9876-5432"
CANARY_URL_HOST = "canary-host.example.invalid"
CANARY_HEADER = "CANARY_RESPONSE_HEADER_VALUE"


def status_error(code, payload=None, *, raw=None, headers=None):
    """실제 `raise_for_status()` 가 만드는 `HTTPStatusError`(요청 주소·헤더·응답 본문이 모두 달려 있다)."""
    request = httpx.Request(
        "POST",
        f"https://{CANARY_URL_HOST}/v1/messages",
        headers={"x-api-key": CANARY_KEY, "authorization": f"Bearer {CANARY_KEY}"},
        json={"messages": [{"role": "user", "content": CANARY_USER}]},
    )
    kwargs = {"json": payload} if raw is None else {"content": raw}
    response = httpx.Response(
        code, request=request, headers={"x-canary": CANARY_HEADER, **(headers or {})}, **kwargs
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("상태 코드가 오류가 아니다")


def api_payload(kind, message=CANARY_MSG):
    return {"type": "error", "error": {"type": kind, "message": message}}


def traced(error):
    t = CallTracer("c1", 0)
    t.observe(body(messages=[{"role": "user", "content": CANARY_USER}]), None, error)
    return t.rows[0]


# ---------- 상태 코드·오류 종류 ----------
@pytest.mark.parametrize(
    ("code", "kind"),
    [
        (400, "invalid_request_error"),
        (401, "authentication_error"),
        (403, "permission_error"),
        (404, "not_found_error"),
        (429, "rate_limit_error"),
        (500, "api_error"),
    ],
)
def test_each_status_code_is_recorded_as_an_integer_with_the_allowed_error_type(code, kind):
    row = traced(status_error(code, api_payload(kind)))
    assert row["ok"] is False and row["error_type"] == "HTTPStatusError"
    assert row["http_status"] == code and type(row["http_status"]) is int
    assert row["api_error_type"] == kind


@pytest.mark.parametrize("kind", sorted(call_trace.API_ERROR_TYPES))
def test_every_allowed_error_type_is_kept_as_is(kind):
    assert traced(status_error(400, api_payload(kind)))["api_error_type"] == kind


@pytest.mark.parametrize(
    "payload",
    [
        None,  # 아래에서 raw 로 처리(빈 본문)
        {},  # error 가 없다
        {"type": "error"},
        {"error": "문자열"},  # error 가 객체가 아니다
        {"error": ["authentication_error"]},
        {"error": {}},  # type 이 없다
        {"error": {"type": None}},
        {"error": {"type": 401}},  # 문자열이 아니다
        {"error": {"type": ["authentication_error"]}},
        {"error": {"type": "Authentication_Error"}},  # 대소문자가 다르면 허용 목록 밖이다
        {"error": {"type": " authentication_error"}},
        {"error": {"type": "authentication_error\n"}},
        {"error": {"type": "evil_type_CANARY"}},  # 허용 목록 밖
        {"error": {"type": "x" * 5000}},
        {"error": {"type": CANARY_KEY}},  # 서버가 키 모양의 글을 돌려줘도 옮기지 않는다
        ["authentication_error"],  # 최상위가 객체가 아니다
        "authentication_error",
    ],
)
def test_a_missing_or_malformed_error_type_is_recorded_as_unknown(payload):
    err = status_error(401, raw=b"") if payload is None else status_error(401, payload)
    row = traced(err)
    assert row["http_status"] == 401 and row["api_error_type"] == "unknown"
    dump = json.dumps(row, ensure_ascii=False)
    assert "CANARY" not in dump and CANARY_KEY not in dump and "x" * 50 not in dump


@pytest.mark.parametrize(
    "raw", [b"<html>Bad Gateway CANARY</html>", b"not json", b"\xff\xfe\x00broken", b"{"]
)
def test_a_non_json_response_body_gives_unknown_and_never_raises(raw):
    row = traced(status_error(502, raw=raw))
    assert row["http_status"] == 502 and row["api_error_type"] == "unknown"
    assert "CANARY" not in json.dumps(row, ensure_ascii=False)


def test_an_unreadable_response_object_still_gives_the_status_or_nothing_and_never_raises():
    class Broken(httpx.Response):
        def json(self, **kwargs):  # noqa: ANN003
            raise RuntimeError(f"읽다가 실패 {CANARY_MSG}")

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = httpx.HTTPStatusError("x", request=request, response=Broken(503, request=request))
    row = traced(err)
    assert row["http_status"] == 503 and row["api_error_type"] == "unknown"
    assert "CANARY" not in json.dumps(row, ensure_ascii=False)


# ---------- 키·개인정보 유출 방지 ----------
@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 500])
def test_no_canary_leaks_into_the_stored_report(code):
    err = status_error(code, api_payload("authentication_error"))
    assert CANARY_KEY in str(err.request.headers) and CANARY_URL_HOST in str(
        err
    )  # 미끼가 실제로 달려 있다
    t = CallTracer("c1", 0)
    t.observe(
        body(
            system=f"SYSMARK {CANARY_KEY}",
            messages=[{"role": "user", "content": CANARY_USER}],
        ),
        None,
        err,
    )
    dump = json.dumps(call_trace.report(t.rows), ensure_ascii=False)
    for needle in (
        CANARY_KEY,
        CANARY_MSG,
        "CANARY_MESSAGE",
        CANARY_USER,
        "CANARY_QUESTION",
        "김비밀",
        "010-9876-5432",
        CANARY_URL_HOST,
        "/v1/messages",
        "x-api-key",
        "authorization",
        "Bearer",
        CANARY_HEADER,
        "x-canary",
        "SYSMARK",
        "invalid x-api-key",
    ):
        assert needle not in dump, needle


def test_an_http_error_row_has_only_the_known_keys():
    row = traced(status_error(429, api_payload("rate_limit_error")))
    assert set(row) == {
        "case_id", "repeat", "call_index", "role", "model", "max_tokens", "ok", "error_type",
        "http_status", "api_error_type",
    }  # fmt: skip


# ---------- 연결 오류·시간 초과·그 밖의 예외는 예전 그대로 ----------
@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError(f"연결 실패 {CANARY_MSG}"),
        httpx.ConnectTimeout(f"시간 초과 {CANARY_MSG}"),
        httpx.ReadTimeout(CANARY_MSG),
        httpx.RemoteProtocolError(CANARY_MSG),
        ValueError(CANARY_MSG),  # 응답이 JSON 이 아닐 때 transport 가 내는 예외
        RuntimeError(CANARY_MSG),
        ConnectionError(CANARY_MSG),
    ],
)
def test_other_errors_keep_only_the_exception_type_as_before(error):
    row = traced(error)
    assert row["ok"] is False and row["error_type"] == type(error).__name__
    assert "http_status" not in row and "api_error_type" not in row
    assert "CANARY" not in json.dumps(row, ensure_ascii=False)


def test_an_exception_that_merely_has_a_response_attribute_is_not_treated_as_an_http_error():
    class Lookalike(Exception):
        response = httpx.Response(401, json=api_payload("authentication_error"))

    row = traced(Lookalike(CANARY_MSG))
    assert row["error_type"] == "Lookalike" and "http_status" not in row


@pytest.mark.parametrize("code", [99, 600, 0])
def test_an_out_of_range_status_code_is_not_recorded(code):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = httpx.HTTPStatusError("x", request=request, response=httpx.Response(200, request=request))
    err.response.status_code = code
    assert call_trace.http_status_of(err) is None
    assert "http_status" not in traced(err)


# ---------- 탭 Agent 가 못 답한 사유(`fallback_reason`): API 오류 메시지 원문은 남기지 않는다 ----------
def _reason_of(rest):
    t = CallTracer("c1", 0)
    t.observe(body(), reply([tool_use("u1", "ask_billing")], "tool_use"))
    t.observe(
        results_body(("u1", ask_content(f"{ASK_PREFIX}{rest}", False), False)), reply([text("끝")])
    )
    return t.rows[1]["tool_results"][0]["fallback_reason"], json.dumps(t.rows, ensure_ascii=False)


@pytest.mark.parametrize(
    ("rest", "expected"),
    [
        (
            f"AI 호출에 실패했어요 (HTTP 401 authentication_error: {CANARY_MSG})",
            "AI 호출에 실패했어요 (HTTP 401 authentication_error)",
        ),
        (
            "AI 호출에 실패했어요 (HTTP 400 invalid_request_error: Your credit balance is too low)",
            "AI 호출에 실패했어요 (HTTP 400 invalid_request_error)",
        ),
        (
            f"AI 호출에 실패했어요 (HTTP 429 rate_limit_error: {CANARY_MSG})",
            "AI 호출에 실패했어요 (HTTP 429 rate_limit_error)",
        ),
        (
            f"AI 호출에 실패했어요 (HTTP 400 : {CANARY_MSG})",
            "AI 호출에 실패했어요 (HTTP 400 unknown)",
        ),  # type 이 비었다
        (
            f"AI 호출에 실패했어요 (HTTP 500 weird_type_CANARY: {CANARY_MSG})",
            "AI 호출에 실패했어요 (HTTP 500 unknown)",
        ),
        (
            f"AI 호출에 실패했어요 (HTTP 502: {CANARY_MSG})",
            "AI 호출에 실패했어요 (HTTP 502 unknown)",
        ),
        ("AI 호출에 실패했어요 (HTTP 503)", "AI 호출에 실패했어요 (HTTP 503 unknown)"),
        (
            f"AI 호출에 실패했어요 (HTTP 401 authentication_error: 첫 줄\n{CANARY_KEY}\n셋째 줄)",
            "AI 호출에 실패했어요 (HTTP 401 authentication_error)",
        ),
    ],
)
def test_the_api_error_message_is_dropped_from_the_fallback_reason(rest, expected):
    reason, dump = _reason_of(rest)
    assert reason == expected
    for needle in (CANARY_MSG, "CANARY", CANARY_KEY, "credit balance", "첫 줄", "셋째 줄"):
        assert needle not in dump


@pytest.mark.parametrize(
    "rest",
    [
        f"AI 호출에 실패했어요 (HTTP abc: {CANARY_MSG})",  # 상태 코드가 숫자가 아니다
        f"AI 호출에 실패했어요 (HTTP 4012 authentication_error: {CANARY_MSG})",
        f"AI 호출에 실패했어요 (HTTP 401 인증 오류!: {CANARY_MSG})",  # 종류 자리가 허용된 글자가 아니다
    ],
)
def test_a_malformed_http_reason_leaves_no_text_at_all(rest):
    reason, dump = _reason_of(rest)
    assert reason is None and "CANARY" not in dump


def test_the_other_fixed_reasons_are_kept_exactly_as_before():
    assert _reason_of("AI 응답이 비어 있어요")[0] == "AI 응답이 비어 있어요"
    assert (
        _reason_of("AI 호출에 실패했어요 (ConnectError)")[0]
        == "AI 호출에 실패했어요 (ConnectError)"
    )
    assert (
        _reason_of("AI 호출에 실패했어요 (HTTPStatusError)")[0]
        == "AI 호출에 실패했어요 (HTTPStatusError)"
    )


# ---------- 요약·하위 호환 ----------
def test_the_summary_counts_http_statuses_only_when_there_are_some():
    t = CallTracer("c1", 0)
    t.observe(body(), None, status_error(429, api_payload("rate_limit_error")))
    t.observe(body(), None, status_error(429, api_payload("rate_limit_error")))
    t.observe(body(), None, status_error(401, api_payload("authentication_error")))
    t.observe(body(), None, httpx.ConnectError("x"))
    summary = call_trace.summarize(t.rows)
    assert summary["http_status_counts"] == {"401": 1, "429": 2}
    assert summary["calls_failed"] == 4 and summary["calls"] == 4


def test_a_summary_without_http_errors_is_exactly_the_old_shape():
    t = CallTracer("c1", 0)
    t.observe(body(), None, RuntimeError("x"))
    assert set(call_trace.summarize(t.rows)) == {
        "calls", "calls_by_role", "stop_reasons", "max_tokens_hits", "calls_without_text",
        "calls_failed", "tool_result_errors", "ask_results_cannot_answer", "trace_errors",
    }  # fmt: skip


def test_rows_from_an_older_diagnostics_file_still_summarize_and_report():
    old_rows = [
        {"case_id": "c", "repeat": 0, "call_index": 0, "role": "main", "model": "m", "max_tokens": 2048,
         "ok": False, "error_type": "HTTPStatusError"},
        {"case_id": "c", "repeat": 0, "call_index": 1, "role": "main", "model": "m", "max_tokens": 2048,
         "ok": True, "stop_reason": "end_turn", "tokens_in": 1, "tokens_out": 1, "output_blocks": {"text": 1},
         "text_chars": 3, "requested_tools": []},
    ]  # fmt: skip
    summary = call_trace.summarize(old_rows)
    assert summary["calls"] == 2 and summary["calls_failed"] == 1
    assert "http_status_counts" not in summary
    assert call_trace.report(old_rows)["schema_version"] == 1


# ---------- 측정기: 동작은 그대로 ----------
def test_the_meter_records_the_same_calls_and_cost_with_and_without_a_tracer(monkeypatch):
    def failing(b, **k):
        raise status_error(401, api_payload("authentication_error"))

    outcomes = []
    for tracer in (None, CallTracer("c", 0)):
        monkeypatch.setattr(transport, "post_messages", failing)
        ledger = runner.default_ledger("real", Decimal("1"))
        with usage.meter_llm_calls(ledger, "c", 0, record_failures=True, tracer=tracer) as meter:
            with pytest.raises(httpx.HTTPStatusError) as raised:
                transport.post_messages(body())
        outcomes.append(
            (
                [(c.model, c.tokens_in, c.tokens_out, c.ok) for c in meter.calls],
                [u.as_dict() for u in ledger.usages],
                str(ledger.total),
                raised.value.response.status_code,
            )
        )
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0] == [("claude-haiku-5-5", 0, 0, False)] and outcomes[0][3] == 401


# ---------- 실행기·CLI(실제 경로, 전송 함수만 가짜): 진단을 켜도 판정·호출 수·비용 기록이 같다 ----------
@pytest.fixture
def real_path(monkeypatch, tmp_path):
    from app.shared.config import settings

    monkeypatch.setenv(real_gate.ENV_NAME, "1")
    monkeypatch.setattr(preflight, "ner_probe", lambda: (True, "시험용 통과"))
    monkeypatch.setattr(settings, "anthropic_api_key", CANARY_KEY)  # 값은 어디에도 남으면 안 된다

    def failing(b, **k):
        raise status_error(401, api_payload("authentication_error"))

    monkeypatch.setattr(transport, "post_messages", failing)
    return tmp_path


def _real_run(monkeypatch, root, run_id, *extra):
    monkeypatch.setattr(cli, "DEFAULT_RESULTS", root / "results")
    monkeypatch.setattr(cli, "DEFAULT_FAKE_RESULTS", root / "results" / "_fake")
    lines: list[str] = []
    code = cli.main(
        ["--real", "--approve-usd", "1", "--case", "b-total", "--run-id", run_id, *extra,
         "--results-dir", str(root / "results")],
        out=lines.append,
    )  # fmt: skip
    return code, "\n".join(lines), root / "results" / run_id


def test_enabling_the_diagnostics_does_not_change_the_verdict_calls_or_cost_records(
    real_path, monkeypatch
):
    code_a, text_a, off = _real_run(monkeypatch, real_path / "a", "http-off")
    code_b, text_b, on = _real_run(monkeypatch, real_path / "b", "http-on", "--call-diagnostics")
    assert code_a == code_b and CANARY_KEY not in text_a + text_b
    assert not (off / "call_diagnostics.json").exists()  # 켜지 않으면 파일이 없다
    for name in ("cases.jsonl", "usage.jsonl", "failures.csv"):
        assert (off / name).read_text("utf-8") == (on / name).read_text("utf-8"), name

    def summary_without_timing(folder):  # 지연 시간 요약(latency_*)은 실행마다 조금씩 다르다
        lines = (folder / "summary.csv").read_text("utf-8").splitlines()
        return [ln for ln in lines if "latency" not in ln]

    assert summary_without_timing(off) == summary_without_timing(on)

    def trajectories(
        folder,
    ):  # 실행 시간(latency_ms)은 진단과 무관하게 실행마다 조금씩 다르다. 나머지는 그대로여야 한다
        rows = [
            json.loads(line)
            for line in (folder / "trajectories.jsonl").read_text("utf-8").splitlines()
        ]
        return [{k: v for k, v in r.items() if k != "latency_ms"} for r in rows]

    assert trajectories(off) == trajectories(on)
    report_off = json.loads((off / "runner_report.json").read_text("utf-8"))
    report_on = json.loads((on / "runner_report.json").read_text("utf-8"))
    for key in ("budget", "cases", "counts"):
        assert report_off[key] == report_on[key]
    assert (
        report_on["budget"]["unconfirmed_calls"] >= 1
    )  # 응답을 못 받은 호출은 최악 비용으로 기록된다(기존 동작)
    manifest_off = json.loads((off / "manifest.json").read_text("utf-8"))
    manifest_on = json.loads((on / "manifest.json").read_text("utf-8"))
    for key in ("cost_usd", "calls", "cases", "prompt_hash", "integrated_prompt_hash"):
        assert manifest_off[key] == manifest_on[key]


def test_the_stored_diagnostics_show_the_status_code_and_nothing_secret(real_path, monkeypatch):
    _, _, on = _real_run(monkeypatch, real_path / "c", "http-diag", "--call-diagnostics")
    text = (on / "call_diagnostics.json").read_text("utf-8")
    data = json.loads(text)
    failed = [c for c in data["calls"] if not c["ok"]]
    assert failed and all(
        c["http_status"] == 401 and c["api_error_type"] == "authentication_error" for c in failed
    )
    assert data["summary"]["http_status_counts"] == {"401": len(failed)}
    for needle in (CANARY_KEY, CANARY_MSG, CANARY_URL_HOST, "x-api-key", CANARY_HEADER, "Bearer"):
        assert needle not in text
    for path in on.iterdir():  # 결과 폴더 어느 파일에도 미끼가 없다
        assert CANARY_KEY not in path.read_text("utf-8", errors="replace"), path.name
