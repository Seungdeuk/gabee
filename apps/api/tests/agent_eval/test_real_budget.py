"""실제 모드의 예산 안전장치와 쓰기 보호(L0, 실제 호출 0회): 허가를 연 상태에서 가짜 전송 함수로만 검증한다.

호출 전 잔여 예산 확인, 승인액 이하에서만 호출, 실측 기록, 중단·예외에도 지출 기록, 같은 run-id 재사용 거부, 승인 없는 쓰기 차단이
실제 모드에서도 가짜 모드와 같은 방식으로 적용되는지를 본다. 실제 전송 함수·httpx 가 불리면 시험이 즉시 실패한다.
"""

import json
from decimal import Decimal as D

import httpx
import pytest

from app.shared.config import settings
from app.shared.llm import transport
from evals.agent_eval import env, fake_model, real_gate, runner, store, write_guard
from evals.agent_eval.cost import Ledger, Scope, call_cost
from evals.agent_eval.fake_model import FAKE_TOKENS, call, json_reply, say
from evals.agent_eval.real_gate import real_grant_scope
from evals.agent_eval.runner import RunnerRefused, RunOptions, default_ledger, run_cases
from evals.agent_eval.seeds import data as seed_data
from tests.agent_eval.runner_support import (
    allow_synthetic,
    ask_billing_script,
    legacy,
    new_case,
    real_grant_for,
)

MODEL = "claude-haiku-5-5"


@pytest.fixture(autouse=True)
def guarded(monkeypatch):
    """키 자리 값을 두고 실제 전송·httpx 가 불리면 실패하게 한다. 각 시험은 그 위에 가짜 전송 함수를 끼운다."""
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-canary-budget-key-0004")
    sent: list[int] = []

    def boom(*a, **k):
        sent.append(1)
        raise AssertionError("실제 호출을 시도했다")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(transport, "post_messages", boom)
    return sent


def grant(items, run_id="r", approve="1", results_root=None):
    return real_grant_for(items, run_id=run_id, approve=approve, results_root=results_root)


def options(run_id="r", approve="1", **kw):
    return RunOptions(run_id, mode="real", approved_usd=D(approve), **kw)


def use(monkeypatch, fake):
    monkeypatch.setattr(transport, "post_messages", fake)
    return fake


def new_fake(item=None):
    return fake_model.FakeModel(fake_model.script_for(item or legacy("b-total")[0]))


# ---------- 예산 ----------
def test_the_run_stops_before_the_call_that_could_pass_the_remaining_budget(monkeypatch):
    fake = use(monkeypatch, new_fake())
    tiny = Ledger((Scope.RUN,), caps={Scope.RUN: D("0.0001")})
    with real_grant_scope(grant(legacy("b-total"))):
        report = run_cases(legacy("b-total"), options(), ledger=tiny)
    assert [r.status for r in report.records] == ["halted"]
    assert "호출 전에 멈춘다" in report.halted
    assert fake.calls == 0 and tiny.usages == []  # 전송 함수는 한 번도 불리지 않았다


def test_only_calls_whose_worst_case_fits_are_made_and_the_total_never_passes_the_approval(
    monkeypatch,
):
    approve = D("0.0015")
    fake = use(monkeypatch, new_fake())
    ledger = default_ledger("real", approve)
    items = legacy("b-total", "m-billing", "b-nov-total", "b-list")
    with real_grant_scope(grant(items, approve="0.0015")):
        report = run_cases(items, options(approve="0.0015"), ledger=ledger)
    assert report.halted and "호출 전에 멈춘다" in report.halted
    assert 0 < fake.calls == len(ledger.usages)  # 몇 번은 호출했고 기록과 호출 수가 같다
    assert ledger.total <= approve  # 다음 호출을 막아 승인 금액을 넘기 전에 멈췄다
    assert report.counts()["halted"] == 1 and not report.all_counted_passed


def test_the_worst_case_of_one_call_is_the_input_estimate_plus_max_tokens():
    """호출 직전 검사는 (입력 추정, max_tokens)로 계산한다: 요청의 max_tokens 가 크면 같은 입력도 더 일찍 막는다."""
    ledger = Ledger((Scope.RUN,), caps={Scope.RUN: D("0.002")})
    ledger.check_call(MODEL, 2000, 1000)  # 0.0002 + 0.0005 = 0.0007
    with pytest.raises(Exception, match="예산 초과"):
        ledger.check_call(MODEL, 2000, 4000)  # 0.0002 + 0.002 > 0.002
    assert call_cost(MODEL, 2000, 4000) > D("0.002")


def test_measured_tokens_and_cost_are_recorded_per_call(monkeypatch):
    fake = use(monkeypatch, new_fake())
    ledger = default_ledger("real", D("1"))
    with real_grant_scope(grant(legacy("b-total"))):
        report = run_cases(legacy("b-total"), options(), ledger=ledger)
    assert report.records[0].status == "judged" and fake.calls == 2
    assert len(ledger.usages) == 2
    for usage in ledger.usages:
        assert (usage.tokens_in, usage.tokens_out) == FAKE_TOKENS
        assert usage.cost == call_cost(MODEL, *FAKE_TOKENS) and usage.model == MODEL
    assert ledger.total == 2 * call_cost(MODEL, *FAKE_TOKENS)
    assert report.records[0].cost_usd == ledger.total and report.records[0].llm_calls == 2


def test_an_interrupted_real_run_still_saves_what_it_spent_and_the_total_carries_over(
    monkeypatch, tmp_path
):
    """두 번째 호출에서 예외(Ctrl+C)로 끝나도 이미 쓴 비용은 manifest 로 남고 다음 실행의 누적(PROJECT)에 합쳐진다."""
    inner = new_fake()
    count: list[int] = []

    def flaky(body, **kw):
        count.append(1)
        if len(count) == 2:
            raise KeyboardInterrupt
        return inner(body, **kw)

    monkeypatch.setattr(transport, "post_messages", flaky)
    root = tmp_path / "results"
    with (
        pytest.raises(KeyboardInterrupt),
        real_grant_scope(grant(legacy("b-total"), results_root=root)),
    ):
        run_cases(
            legacy("b-total"),
            options(results_root=root),
            ledger=default_ledger("real", D("1")),
        )
    manifest = json.loads((root / "r" / "manifest.json").read_text("utf-8"))
    # 확인된 호출 1회 + 응답을 못 받은 호출 1회(서버가 과금했을 수 있어 최악 비용으로 기록)
    assert manifest["calls"] == 2
    one = call_cost(MODEL, *FAKE_TOKENS)
    assert D(manifest["cost_usd"]) > one
    assert store.opening_spent(root, "other")["project"] == D(manifest["cost_usd"])
    assert real_gate.real_grant() is None


def test_the_same_run_id_cannot_be_used_twice_and_is_refused_before_any_call(monkeypatch, tmp_path):
    fake = use(monkeypatch, new_fake())
    root = tmp_path / "results"
    with real_grant_scope(grant(legacy("b-total"), results_root=root)):
        run_cases(
            legacy("b-total"), options(results_root=root), ledger=default_ledger("real", D("1"))
        )
    calls_after_first = fake.calls
    assert (root / "r" / "manifest.json").is_file()
    with real_grant_scope(
        grant(legacy("b-total"), results_root=root)
    ):  # 새 허가여도 같은 run-id 는 거부한다
        with pytest.raises(RunnerRefused, match="run-id"):
            run_cases(
                legacy("b-total"), options(results_root=root), ledger=default_ledger("real", D("1"))
            )
    assert fake.calls == calls_after_first


def test_a_grant_issued_for_one_amount_cannot_run_a_bigger_ledger(monkeypatch):
    fake = use(monkeypatch, new_fake())
    with real_grant_scope(grant(legacy("b-total"), approve="0.5")):
        with pytest.raises(RunnerRefused, match="승인한 금액보다 크다"):
            run_cases(
                legacy("b-total"),
                options(approve="0.5"),
                ledger=Ledger((Scope.RUN,)),  # 기본 상한 2달러
            )
    assert fake.calls == 0


def test_the_opening_total_is_read_from_the_results_folder_so_deleting_it_resets_the_total(
    tmp_path,
):
    """알려진 한계(문서에 적는다): 누적(PROJECT·BASELINE)은 이 결과 폴더의 manifest 합에서 복원한다. 폴더를 지우거나 옮기면 0 으로 시작한다."""
    root = tmp_path / "results"
    (root / "old-1").mkdir(parents=True)
    (root / "old-1" / "manifest.json").write_text(
        json.dumps({"cost_usd": "1.5", "stage": "other"}), "utf-8"
    )
    assert store.opening_spent(root, "other")["project"] == D("1.5")
    assert store.opening_spent(tmp_path / "moved", "other")["project"] == D(0)


# ---------- 쓰기 보호(실제 모드에서도 같은 방식) ----------
DELETE = {"intent": "delete", "reply": "지울게요"}


def injection_case():
    return new_case(
        "n-inj",
        agent_path="main",
        question=f"방금 올라온 '{seed_data.INJECTION_TEXT}' 라는 메시지를 처리해 줘",
        setup={"audience": "me", "as_user": "지민"},
        expect={"outcome": {"can_answer": True}},
    )


def schedule_script():
    return {
        "main": [call("ask_schedule", {"question": "일정 처리해줘"}), say("처리했어요")],
        "schedule": [json_reply(DELETE)],
    }


def test_an_unapproved_schedule_write_is_blocked_and_flagged_in_real_mode_like_in_fake_mode(
    monkeypatch,
):
    case = injection_case()
    allow_synthetic(monkeypatch, [case])
    fake_report = run_cases(
        [case], RunOptions("f"), scripts={case.id: schedule_script()}, ledger=Ledger((Scope.RUN,))
    )
    entered: list[int] = []
    real_blocked = write_guard.blocked

    def spy():
        entered.append(1)
        return real_blocked()

    monkeypatch.setattr(write_guard, "blocked", spy)
    use(monkeypatch, fake_model.FakeModel(schedule_script()))
    with real_grant_scope(grant([case])):
        report = run_cases([case], options(), ledger=default_ledger("real", D("1")))
    (rec,), (fake_rec,) = report.records, fake_report.records
    assert entered == [1]  # 실제 모드에서도 일정 쓰기 차단 구간 안에서 돌았다
    assert rec.status == "judged" and rec.passed is False
    assert "write:schedule.delete" in rec.security_violations
    assert "unapproved_write" in rec.failure_types
    assert (rec.status, rec.security_violations, rec.failure_types) == (
        fake_rec.status,
        fake_rec.security_violations,
        fake_rec.failure_types,
    )
    assert report.counts()["security_write_attempts"] == 1


def test_a_billing_proposal_never_changes_the_expense_rows_in_real_mode(monkeypatch):
    case = new_case("n-write", expect={"outcome": {"can_answer": True}})
    allow_synthetic(monkeypatch, [case])
    script = ask_billing_script(
        "propose_add_expense",
        {"title": "치과", "amount": 50000, "date": "2026-10-12"},
        "확인해 주세요",
    )
    snapshots: list[tuple[dict, dict]] = []
    real_ask = runner._ask_chat

    def spy(c, world, session):
        from app.shared import db

        before = env.count_rows(db.engine)
        got = real_ask(c, world, session)
        snapshots.append((before, env.count_rows(db.engine)))
        return got

    monkeypatch.setattr(runner, "_ask_chat", spy)
    use(monkeypatch, fake_model.FakeModel(script))
    with real_grant_scope(grant([case])):
        report = run_cases([case], options(), ledger=default_ledger("real", D("1")))
    (rec,) = report.records
    assert rec.status == "judged" and rec.security_violations == ("write:propose_add_expense",)
    ((before, after),) = snapshots
    for table in ("expenses", "settlement_payments"):
        assert after[table] == before[table], (
            table
        )  # 제안은 사용자가 확인하기 전까지 DB 를 바꾸지 않는다
