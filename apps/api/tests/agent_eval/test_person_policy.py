"""가족 이름(합성 PERSON) 발신 기록 정책과 예산 중단 분류(L0, 가짜 전송, 실제 호출 0회).

정책: 합성 PERSON 의 외부 전송은 실제 개인정보 유출과 같게 집계하지 않는다. 가명화 대상 경로(family_chat·schedule)의 본문에 원문이 남으면 "가명화 정책 미준수"로
별도 기록하고(실패 아님), 메인은 ADR 0014 의 의도된 예외, 정산은 알려진 갭으로 분류한다. 이 PR 은 앱의 가명화 동작을 바꾸지 않는다."""

import json
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.shared.config import settings
from app.shared.llm import transport
from evals.agent_eval import fake_model, preflight, real_gate, runner, usage
from evals.agent_eval.cost import Ledger, Scope
from evals.agent_eval.runner import RunOptions, default_ledger, run_cases
from tests.agent_eval.runner_support import (
    allow_synthetic,
    ask_billing_script,
    legacy,
    new_case,
    real_grant_for,
)
from tests.agent_eval.test_preflight import CANARY, make_input

MODEL = "claude-haiku-5-5"


def body(text, **over):
    base = {
        "model": settings.llm_model,
        "max_tokens": 1024,
        "system": "담당",
        "messages": [{"role": "user", "content": text}],
    }
    base.update(over)
    return base


def stub(monkeypatch, pairs, case_id="b-total"):
    """pairs = [(stage, body)] 를 한 사례의 가짜 전송이 받은 요청으로 돌려주는 가짜 실행 결과."""
    fake = SimpleNamespace(agents=[s for s, _ in pairs], bodies=[b for _, b in pairs])
    report = SimpleNamespace(
        records=[SimpleNamespace(case_id=case_id, status="judged")], fakes={(case_id, 0): fake}
    )
    monkeypatch.setattr(runner, "run_cases", lambda *a, **k: report)


def rows_of(check_and_bodies):
    return {(r[0], r[1]): r for r in check_and_bodies[1].person_rows}


def test_person_originals_are_classified_per_stage_and_never_make_the_check_fail(
    tmp_path, monkeypatch
):
    stub(
        monkeypatch,
        [
            ("main", body("지민 님의 일정은 지민 이 정리해요")),
            ("billing", body("수진 이 낸 장보기")),
            ("family_chat", body("지민 이 말했어요")),
            ("schedule", body("[P1] 가 말했어요")),
        ],
    )
    out = preflight._fake_pass(make_input(tmp_path))
    check = out[0]
    assert check.status == preflight.PASS, check.detail  # 실패가 아니라 기록이다
    rows = rows_of(out)
    assert rows[("b-total", "main")][2] == 2 and "ADR 0014" in rows[("b-total", "main")][3]
    assert rows[("b-total", "billing")][2] == 1 and "알려진 갭" in rows[("b-total", "billing")][3]
    assert rows[("b-total", "family_chat")][2] == 1
    assert "가명화 정책 미준수" in rows[("b-total", "family_chat")][3]
    assert (
        rows[("b-total", "schedule")][2] == 0 and "미준수" not in rows[("b-total", "schedule")][3]
    )
    assert "가명화 정책 미준수(기록)" in check.detail and "실패 아님" in check.detail
    assert "의도된 예외" in check.detail and "알려진 갭" in check.detail


def test_a_schedule_body_with_a_raw_name_is_recorded_as_a_policy_miss(tmp_path, monkeypatch):
    stub(monkeypatch, [("schedule", body("수진 이 예약했어요"))])
    out = preflight._fake_pass(make_input(tmp_path))
    assert out[0].status == preflight.PASS
    assert "가명화 정책 미준수" in rows_of(out)[("b-total", "schedule")][3]


def test_high_risk_values_still_fail_even_with_the_person_policy(tmp_path, monkeypatch):
    stub(monkeypatch, [("family_chat", body("지민 번호는 010-1234-5678"))])
    check = preflight._fake_pass(make_input(tmp_path))[0]
    assert check.status == preflight.FAIL and "PHONE" in check.detail


def test_the_record_keeps_the_person_report_as_a_separate_field(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "ner_probe", lambda: (True, "시험용"))
    monkeypatch.setattr(settings, "anthropic_api_key", CANARY)
    stub(monkeypatch, [("main", body("지민")), ("family_chat", body("수진"))])
    report = preflight.run_preflight(make_input(tmp_path))
    assert report.person_rows and report.record is not None
    assert report.record.person_report == tuple(report.person_rows)
    text = "\n".join(report.lines())
    assert "PERSON 원문 발신 기록" in text and "의도된 예외" in text and CANARY not in text


def test_a_real_pilot_like_pass_labels_every_body_with_its_stage(tmp_path):
    out = preflight._fake_pass(make_input(tmp_path))
    assert out[0].status == preflight.PASS, out[0].detail
    assert out[1].person_rows and {r[1] for r in out[1].person_rows} <= {
        "main",
        "billing",
        "family_chat",
        "schedule",
    }


# ---------- 2. 모든 하위 Agent 호출은 같은 측정기·호출 직전 검사를 지난다 ----------
@pytest.fixture
def guarded(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-canary-person-0006")
    monkeypatch.setattr(transport, "post_messages", lambda *a, **k: pytest.fail("실제 호출"))


def test_main_and_every_sub_agent_call_goes_through_the_meter_and_the_pre_call_check(
    monkeypatch, guarded
):
    case = new_case("n-sub", expect={"outcome": {"can_answer": True}})
    allow_synthetic(monkeypatch, [case])
    fake = fake_model.FakeModel(ask_billing_script())
    monkeypatch.setattr(transport, "post_messages", fake)
    ledger = default_ledger("real", D("1"))
    checks: list[int] = []
    real_check = ledger.check_call
    ledger.check_call = lambda *a, **k: (checks.append(1), real_check(*a, **k))[1]
    with real_gate.real_grant_scope(real_grant_for([case])):
        run_cases([case], RunOptions("r", mode="real", approved_usd=D("1")), ledger=ledger)
    assert fake.agents == ["main", "billing", "billing"]  # 메인 -> ask_billing -> 하위 Agent 두 번
    assert fake.calls == len(ledger.usages) == len(checks) == 3
    assert not any(u.unconfirmed for u in ledger.usages)


def test_the_schedule_structured_output_call_is_metered_too(monkeypatch, guarded):
    from evals.agent_eval.fake_model import call, json_reply, say

    case = new_case(
        "n-sch", agent_path="main", expect={"outcome": {"can_answer": True}}, question="일정 알려줘"
    )
    allow_synthetic(monkeypatch, [case])
    script = {
        "main": [call("ask_schedule", {"question": "일정"}), say("있어요")],
        "schedule": [json_reply({"intent": "query", "reply": "없어요"})],
    }
    fake = fake_model.FakeModel(script)
    monkeypatch.setattr(transport, "post_messages", fake)
    ledger = default_ledger("real", D("1"))
    with real_gate.real_grant_scope(real_grant_for([case])):
        run_cases([case], RunOptions("r", mode="real", approved_usd=D("1")), ledger=ledger)
    assert "schedule" in fake.agents and fake.calls == len(ledger.usages) >= 2


def test_the_metered_transport_functions_are_the_only_model_paths_of_the_app():
    """코드로 확인한 모델 호출 경로: agent._post·client._post·doc_ai·rag_chat 은 모두 transport.post_messages 를 거친다(측정 대상).
    측정기를 우회하는 경로는 `shared/llm/jev.py`(직접 httpx)뿐이고 평가 경로에서 쓰이지 않는다."""
    from pathlib import Path

    root = Path(runner.__file__).resolve().parents[2] / "app"
    direct = sorted(
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if "tests" not in p.parts
        and "httpx.post(" in p.read_text("utf-8")
        and p.name != "transport.py"
    )
    assert direct == ["shared\\llm\\jev.py", "shared\\push.py"] or direct == [
        "shared/llm/jev.py",
        "shared/push.py",
    ]  # push 는 모델 호출이 아니다(네트워크 차단이 막는다)


# ---------- 2. 예산 중단은 Task Success 실패와 별도다 ----------
def test_a_budget_halt_is_counted_apart_from_failures_and_the_task_success_denominator(tmp_path):
    items = legacy("b-total", "b-nov-total", "m-billing", "b-list")
    # 첫 사례들은 끝나고 그 뒤에 예산 중단. 2026-11-25: Agent 요청 max_tokens 10000 으로 호출 한 번의 최악 비용이 약 $0.0053 이라 상한을 그에 맞춰 올렸다(이전 $0.0025)
    cap = Ledger((Scope.RUN,), caps={Scope.RUN: D("0.0065")})
    report = runner.run_cases(items, RunOptions("h", results_root=tmp_path), ledger=cap)
    c = report.counts()
    assert c["halted"] == 1 and c["failed"] == 0 and c["passed"] == c["judged"] >= 1
    lines = "\n".join(report.summary_lines())
    assert "예산 중단 1건" in lines
    saved = json.loads((report.run_dir / runner.REPORT_FILE).read_text("utf-8"))
    assert saved["counts"]["halted"] == 1 and saved["counts"]["failed"] == 0
    summary = dict(
        line.split(",", 1)
        for line in (report.run_dir / "summary.csv").read_text("utf-8").splitlines()[1:]
    )
    assert summary["runner.halted"] == "1" and summary["runner.failed"] == "0"
    # Task Success 분모(저장·지표 대상)에는 끝난 사례만 들어가고 중단된 사례는 없다
    assert int(summary["metrics.runs"]) == len(report.stored) == c["judged"]
    halted_ids = {r.case_id for r in report.records if r.status == "halted"}
    assert halted_ids and not halted_ids & {s.case.id for s in report.stored}


def test_the_unconfirmed_record_tests_still_exist():
    """응답 해석 실패 경로의 이중 기록·누락 방지는 test_real_final.py 가 고정한다."""
    from tests.agent_eval import test_real_final

    assert hasattr(
        test_real_final, "test_an_exception_after_the_confirmed_record_does_not_record_again"
    )
    assert hasattr(test_real_final, "test_a_transport_exception_is_still_recorded_exactly_once")
    assert usage.estimate_input_tokens({"messages": "x"}) > 0


# ---------- 고위험 탐지 실패 메시지의 진단 정보는 값을 새지 않는다 ----------
LEAK_BODIES = [
    "연락처 010-1234-5678 010-9876-5432 입니다",  # 공백으로 이어진 전화번호 두 개
    "계좌 110-123-456789, 010-5555-6666 로 보내요",  # 쉼표로 이어진 계좌 + 전화
]
LEAK_PIECES = [
    "010-1234-5678",
    "010-9876-5432",
    "5678",
    "5432",
    "110-123-456789",
    "456789",
    "010-5555-6666",
    "6666",
]


@pytest.mark.parametrize("text", LEAK_BODIES)
def test_the_failure_diagnostics_never_leak_adjacent_high_risk_values(
    text, tmp_path, monkeypatch, caplog
):
    import logging

    stub(monkeypatch, [("family_chat", body(text))])
    with caplog.at_level(logging.DEBUG):
        out = preflight._fake_pass(make_input(tmp_path))
    check = out[0]
    assert check.status == preflight.FAIL
    everything = "\n".join(
        [check.detail, *(" | ".join(map(str, r)) for r in out[1].person_rows), caplog.text]
    )
    for piece in LEAK_PIECES:
        assert piece not in everything, piece  # 값 전체·끝자리 숫자 어디에도 없다
    # 진단 정보(경로·규칙·점수·값 길이·종류)는 남아 있다
    assert "본문(family_chat)" in check.detail and "점수" in check.detail
    assert "PHONE(" in check.detail and "길이" in check.detail
    assert "앞 글 종류:" in check.detail


def test_report_lines_and_exception_messages_do_not_leak_either(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "ner_probe", lambda: (True, "시험용"))
    monkeypatch.setattr(settings, "anthropic_api_key", CANARY)
    stub(monkeypatch, [("family_chat", body(LEAK_BODIES[0]))])
    report = preflight.run_preflight(make_input(tmp_path))
    text = "\n".join(report.lines())
    assert not report.ok
    for piece in LEAK_PIECES[:4]:
        assert piece not in text, piece


def test_the_context_summary_keeps_only_character_classes_and_masks_every_high_risk_span():
    chunk = "연락처 abc 010-1234-5678 010-9876-5432 끝"
    spans = [
        (chunk.index("010-1234"), chunk.index("010-1234") + 13),
        (chunk.index("010-9876"), chunk.index("010-9876") + 13),
    ]
    second = spans[1][0]
    got = preflight._context_summary(chunk, second, spans)
    assert len(got) <= preflight.CONTEXT_CHARS and set(got) <= set("9aA가_.#")
    assert "5678" not in got and "9" not in got.replace("#", "")  # 앞 값의 숫자는 가려졌다
    assert got == "#" * 11 + "_"  # 앞 값은 모두 가려지고(숫자 없음) 공백 하나만 종류로 남는다
