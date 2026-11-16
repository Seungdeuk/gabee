"""E7a 리뷰 반영 시험(L0, 실제 호출 0회): mode 검증, 허가·사전 점검 기록 위조 방지, 소진된 허가, 커밋 대조, 내용 해시, 반복 상한,
재시도 끄기, 미확인 호출의 보수적 비용 기록, 사전 점검의 호출 수 계산."""

import json
from decimal import Decimal as D

import httpx
import pytest

from app.shared.config import settings
from app.shared.llm import transport
from evals.agent_eval import (
    case_files,
    cli,
    dev_cases,
    fake_model,
    network,
    preflight,
    real_gate,
    runner,
    usage,
)
from evals.agent_eval.cost import Ledger, Scope, call_cost
from evals.agent_eval.real_gate import RealGateRefused, real_grant_scope
from evals.agent_eval.runner import RunnerRefused, RunOptions, default_ledger, run_cases
from tests.agent_eval.runner_support import allow_synthetic, legacy, new_case, real_grant_for

MODEL = "claude-haiku-5-5"


@pytest.fixture(autouse=True)
def guarded(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-canary-hardening-0005")
    sent: list[int] = []

    def boom(*a, **k):
        sent.append(1)
        raise AssertionError("실제 호출을 시도했다")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(transport, "post_messages", boom)
    return sent


def options(run_id="r", approve="1", **kw):
    return RunOptions(run_id, mode="real", approved_usd=D(approve), **kw)


def b_total():
    return legacy("b-total")


# ---------- 1. mode 검증 ----------
@pytest.mark.parametrize("mode", ["REAL", "Real", "", None, "x", " real", "fake "])
def test_a_mode_other_than_fake_or_real_is_refused_without_a_call(mode, guarded):
    opts = RunOptions("r", mode=mode, approved_usd=D("1"))
    with pytest.raises(RunnerRefused, match="mode"):
        run_cases(b_total(), opts, ledger=default_ledger("real", D("1")))
    with pytest.raises(RunnerRefused, match="mode"):
        with runner._session(opts):
            pytest.fail("세션이 열리면 안 된다")
    assert guarded == []


@pytest.mark.parametrize("mode", ["REAL", "x", None])
def test_an_invalid_mode_is_refused_even_while_a_grant_is_active(mode, monkeypatch, guarded):
    items = b_total()
    with real_grant_scope(real_grant_for(items)):
        with pytest.raises(RunnerRefused, match="mode"):
            run_cases(items, RunOptions("r", mode=mode, approved_usd=D("1")))
    assert guarded == []


def test_fake_and_real_are_decided_in_one_function():
    assert real_gate.is_fake("fake") is True
    assert all(real_gate.is_fake(m) is False for m in ("real", "REAL", "", None, "x"))


# ---------- 5. 위조 방지(nonce) ----------
def test_a_hand_made_preflight_record_is_refused():
    items = b_total()
    forged = real_gate.PreflightRecord(
        "r", D("1"), "legacy", frozenset({"b-total"}), D("0.01"), runner.case_fingerprint(items), 1
    )
    with pytest.raises(RealGateRefused, match="사전 점검"):
        real_gate.issue_grant(
            approve_usd="1",
            split="legacy",
            case_ids=["b-total"],
            known_ids=["b-total"],
            run_id="r",
            preflight=forged,
            content_hash=runner.case_fingerprint(items),
            environ={real_gate.ENV_NAME: "1"},
        )


def test_a_preflight_record_can_be_used_for_one_grant_only():
    items = b_total()
    digest = runner.case_fingerprint(items)
    record = real_gate._mint_preflight(
        "r", D("1"), "legacy", frozenset({"b-total"}), D("0.01"), digest, 1
    )
    kw = dict(
        approve_usd="1",
        split="legacy",
        case_ids=["b-total"],
        known_ids=["b-total"],
        run_id="r",
        preflight=record,
        content_hash=digest,
        environ={real_gate.ENV_NAME: "1"},
    )
    real_gate.issue_grant(**kw)
    with pytest.raises(RealGateRefused, match="사전 점검"):
        real_gate.issue_grant(**kw)


def test_a_hand_made_grant_is_not_recognised_by_scope_run_or_network(guarded):
    items = b_total()
    real = real_grant_for(items)
    forged = real_gate.RealGrant(
        real.approved_usd, real.case_ids, real.split, real.run_id, real.issued_at, True,
        content_hash=real.content_hash, repeat=1,
    )  # fmt: skip
    with pytest.raises(RealGateRefused, match="발급"):
        with real_grant_scope(forged):
            pytest.fail("열리면 안 된다")
    with pytest.raises(RealGateRefused, match="발급"):
        real_gate.check_run(
            forged, approved_usd=D("1"), run_id="r", splits={"legacy"}, case_ids={"b-total"},
            results_root=None, content_hash=real.content_hash, repeats=1,
        )  # fmt: skip
    with pytest.raises(RealGateRefused):
        with network.block_network(real_gate.REAL_HOSTS):
            pass
    with pytest.raises(RunnerRefused):
        run_cases(items, options(), ledger=default_ledger("real", D("1")))
    assert guarded == []


def test_a_grant_cannot_be_issued_without_the_environment_variable_even_with_a_record():
    items = b_total()
    digest = runner.case_fingerprint(items)
    record = real_gate._mint_preflight(
        "r", D("1"), "legacy", frozenset({"b-total"}), D("0.01"), digest, 1
    )
    with pytest.raises(RealGateRefused, match=real_gate.ENV_NAME):
        real_gate.issue_grant(
            approve_usd="1", split="legacy", case_ids=["b-total"], known_ids=["b-total"],
            run_id="r", preflight=record, content_hash=digest, environ={},
        )  # fmt: skip


# ---------- 6. 소진된 허가 ----------
def test_a_spent_grant_opens_nothing_any_more(monkeypatch, guarded):
    items = b_total()
    fake = fake_model.FakeModel(fake_model.script_for(items[0]))
    monkeypatch.setattr(transport, "post_messages", fake)
    grant = real_grant_for(items)
    with real_grant_scope(grant):
        run_cases(items, options(), ledger=default_ledger("real", D("1")))
        assert grant.consumed
        with pytest.raises(RealGateRefused):
            real_gate.require_active()
        with pytest.raises(RealGateRefused):
            with network.block_network(real_gate.REAL_HOSTS):
                pass
        with pytest.raises(RunnerRefused):
            with runner._session(options()):
                pytest.fail("열리면 안 된다")
    with pytest.raises(RealGateRefused):
        with real_grant_scope(grant):
            pass
    assert real_gate.real_grant() is None


# ---------- 3. 커밋된 목록 대조 ----------
def test_committed_cases_pass_the_verification():
    legacy_items = b_total()
    runner.verify_committed(legacy_items, "legacy")
    dev = case_files.load_cases(dev_cases.CASES_DEV_PATH, "dev")[:2]
    runner.verify_committed(dev, "dev")


def test_a_val_case_disguised_as_dev_is_refused(monkeypatch, guarded):
    disguised = new_case("s-val-01-secret-01", split="dev")
    grant = real_grant_for([disguised])
    with real_grant_scope(grant):
        with pytest.raises(RunnerRefused, match="커밋"):
            run_cases([disguised], options(), ledger=default_ledger("real", D("1")))
    assert guarded == []


def test_a_committed_dev_case_with_changed_content_is_refused(guarded):
    real_case = case_files.load_cases(dev_cases.CASES_DEV_PATH, "dev")[0]
    changed = real_case.model_copy(update={"question": real_case.question + " (바꿈)"})
    with real_grant_scope(real_grant_for([changed])):
        with pytest.raises(RunnerRefused, match="다르다"):
            run_cases([changed], options(), ledger=default_ledger("real", D("1")))
    assert guarded == []


def test_a_legacy_case_with_changed_content_is_refused(guarded):
    item = b_total()[0]
    asked = item.case.model_copy(update={"question": item.case.question + " 바꿈"})
    from evals.agent_eval import adapter

    changed = adapter.LegacyCase(asked, item.checks)
    with real_grant_scope(real_grant_for([changed])):
        with pytest.raises(RunnerRefused, match="다르다"):
            run_cases([changed], options(), ledger=default_ledger("real", D("1")))
    assert guarded == []


# ---------- 7. 내용 해시와 쓰기 사례 제외 ----------
def test_the_grant_is_bound_to_the_content_of_the_selected_cases(monkeypatch, guarded):
    a = new_case("n-1", question="질문 하나")
    b = new_case("n-1", question="질문 둘")
    allow_synthetic(monkeypatch, [a, b])
    with real_grant_scope(real_grant_for([a])):
        with pytest.raises(RunnerRefused, match="내용"):
            run_cases([b], options(), ledger=default_ledger("real", D("1")))
    assert guarded == []


def test_a_write_expecting_case_is_refused_again_in_the_runner(monkeypatch, guarded):
    writer = new_case("n-w", expect={"tools": {"required": ["propose_add_expense"]}})
    allow_synthetic(monkeypatch, [writer])
    with real_grant_scope(real_grant_for([writer])):
        with pytest.raises(RunnerRefused, match="쓰기"):
            run_cases([writer], options(), ledger=default_ledger("real", D("1")))
    assert guarded == []


# ---------- 8. 반복 상한 ----------
def test_repeats_are_capped_for_real_calls():
    assert real_gate.MAX_REAL_REPEAT == 3
    ok = dict(approve_usd="1", split="dev", case_ids=["a"], environ={real_gate.ENV_NAME: "1"})
    assert real_gate.check_request(**ok, repeat=3) == D("1")
    with pytest.raises(RealGateRefused, match="반복"):
        real_gate.check_request(**ok, repeat=4)


def test_the_cli_refuses_more_than_the_allowed_repeats(tmp_path):
    lines: list[str] = []
    argv = ["--real", "--approve-usd", "1", "--case", "b-total", "--repeat", "4"]
    code = cli.main([*argv, "--results-dir", str(tmp_path / "r")], out=lines.append)
    assert code == cli.REFUSED and "반복" in "\n".join(lines)


def test_the_runner_refuses_repeats_that_differ_from_the_grant(guarded):
    items = b_total()
    with real_grant_scope(real_grant_for(items, repeat=1)):
        with pytest.raises(RunnerRefused, match="반복"):
            run_cases(items, options(repeats=2), ledger=default_ledger("real", D("1")))
    assert guarded == []


# ---------- 9. --preflight 는 환경변수를 요구하지 않는다 ----------
def test_preflight_runs_without_the_environment_variable_and_marks_it_as_needed_for_real(
    tmp_path, monkeypatch
):
    monkeypatch.delenv(real_gate.ENV_NAME, raising=False)
    monkeypatch.setattr(cli, "DEFAULT_RESULTS", tmp_path / "results")
    monkeypatch.setattr(preflight, "ner_probe", lambda: (True, "시험용 통과"))
    lines: list[str] = []
    argv = ["--preflight", "--approve-usd", "1", "--case", "b-total"]
    code = cli.main([*argv, "--results-dir", str(tmp_path / "results")], out=lines.append)
    text = "\n".join(lines)
    assert code == 0, text
    assert "실호출 시 필요" in text and real_gate.ENV_NAME in text and "[경고]" in text
    code, text = (
        cli.main(
            [
                *argv[:0],
                "--real",
                "--approve-usd",
                "1",
                "--case",
                "b-total",
                "--results-dir",
                str(tmp_path / "results"),
            ],
            out=lines.append,
        ),
        "\n".join(lines),
    )
    assert code == cli.REFUSED  # --real 은 환경변수가 필수


# ---------- 2a. 재시도 끄기 ----------
def test_retries_are_switched_off_only_inside_the_context_and_restored():
    seen: list[dict] = []

    def inner(body, *, timeout=60.0, retry=False):
        seen.append({"retry": retry, "timeout": timeout})
        return {}

    original = transport.post_messages
    transport.post_messages = inner
    try:
        with usage.retries_off():
            transport.post_messages({}, timeout=5.0, retry=True)
            transport.post_messages({})
        assert transport.post_messages is inner
        transport.post_messages({}, retry=True)
    finally:
        transport.post_messages = original
    assert [s["retry"] for s in seen] == [False, False, True] and seen[0]["timeout"] == 5.0


def test_retries_off_leaves_a_transport_without_a_retry_parameter_alone():
    got: list[int] = []

    def plain(body):
        got.append(1)
        return {}

    original = transport.post_messages
    transport.post_messages = plain
    try:
        with usage.retries_off():
            transport.post_messages({"x": 1})
    finally:
        transport.post_messages = original
    assert got == [1]


def test_a_real_session_calls_the_transport_with_retry_off(monkeypatch):
    items = b_total()
    inner = fake_model.FakeModel(fake_model.script_for(items[0]))
    kinds: list[object] = []

    def recording(body, **kw):
        kinds.append(kw.get("retry"))
        return inner(body, **kw)

    monkeypatch.setattr(transport, "post_messages", recording)
    with real_grant_scope(real_grant_for(items)):
        run_cases(items, options(), ledger=default_ledger("real", D("1")))
    assert kinds and all(k is False or k is None for k in kinds)
    assert transport.post_messages is recording  # 세션이 끝나면 원복


# ---------- 2b. 미확인 호출의 보수적 비용 ----------
def test_a_transport_failure_is_recorded_at_the_worst_case_cost_and_marked(tmp_path, monkeypatch):
    items = b_total()

    def failing(body, **kw):
        raise httpx.ReadTimeout("응답 없음")

    monkeypatch.setattr(transport, "post_messages", failing)
    root = tmp_path / "results"
    ledger = default_ledger("real", D("1"))
    with real_grant_scope(real_grant_for(items, results_root=root)):
        report = run_cases(items, options(results_root=root), ledger=ledger)
    assert ledger.usages and all(u.unconfirmed for u in ledger.usages)
    first = ledger.usages[0]
    assert first.tokens_out > 0 and first.cost == call_cost(
        MODEL, first.tokens_in, first.tokens_out
    )
    assert ledger.total == sum(u.cost for u in ledger.usages) > 0
    saved = json.loads((report.run_dir / runner.REPORT_FILE).read_text("utf-8"))
    assert saved["budget"]["unconfirmed_calls"] == len(ledger.usages)
    manifest = json.loads((report.run_dir / "manifest.json").read_text("utf-8"))
    assert D(manifest["cost_usd"]) == ledger.total


def test_a_confirmed_response_is_not_marked_and_fake_mode_never_records_failures(monkeypatch):
    items = b_total()
    fake = fake_model.FakeModel(fake_model.script_for(items[0]))
    monkeypatch.setattr(transport, "post_messages", fake)
    ledger = default_ledger("real", D("1"))
    with real_grant_scope(real_grant_for(items)):
        run_cases(items, options(), ledger=ledger)
    assert ledger.usages and not any(u.unconfirmed for u in ledger.usages)
    # 가짜 모드의 대본 바닥남(예외)은 기록장에 쓰지 않는다(기존 동작)
    fake_ledger = Ledger((Scope.RUN,))
    report = run_cases(
        [new_case("n-x")], RunOptions("f"), scripts={"n-x": {"main": []}}, ledger=fake_ledger
    )
    assert report.records and not any(u.unconfirmed for u in fake_ledger.usages)


# ---------- 2c. 호출 수 계산 ----------
def test_the_structural_maximum_is_read_from_the_code_constants():
    from app.features.ai_assistant.knowledge import rag_chat

    steps = rag_chat.MAX_STEPS
    sub = preflight.sub_agent_steps()
    assert sub == 4
    expected = steps + 1 + (steps - 1) * (sub + 2 * sub + 1)
    assert preflight.structural_max_calls() == expected == 44


def test_the_main_loop_worst_includes_the_verification_call_and_theory_is_informational_only():
    a = preflight.main_loop_worst("claude-haiku-5-5", 9, 1, 16479, 2048)
    assert a == 9 * 1 * (4 + 1) * call_cost("claude-haiku-5-5", 16479, 2048)
    t = preflight.structural_worst_case("claude-haiku-5-5", 9, 1, 16479, 2048)
    assert t == 9 * 44 * call_cost("claude-haiku-5-5", 16479, 2048) and t > D("0.20") > a
