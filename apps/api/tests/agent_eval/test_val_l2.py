"""검증셋 18건 L2 실행 시험(L0 규칙: 가짜 모델·임시 SQLite·네트워크 차단, 실제 LLM 없음, val 실모델 실행 없음).

가짜 모델 -> 실제 도구 -> w2 합성 DB -> 관찰 -> 채점 -> 저장 이 검증 18건 전부에서 이어지는지 본다. 정상 대본(`val_scripts.SCRIPTS`)의 통과는 "연결이 된다"는 뜻이고
Agent 의 정확도가 아니다(`val_scripts` 머리말). 가짜 모드의 val 은 목적(`purpose`)을 밝혀야 돌고(`runner._resolve`), 실호출 게이트(`real_gate.ALLOWED_SPLITS`)는 바뀌지 않았다.
"""

import json
import re

import pytest

from app.shared.llm import transport
from evals.agent_eval import case_files as cf
from evals.agent_eval import (
    cli,
    dev_cases,
    dev_scripts,
    exposure,
    fault_injection,
    preflight,
    real_gate,
    runner,
    val_cases,
    val_scripts,
)
from evals.agent_eval.cost import Ledger, Scope
from evals.agent_eval.preflight import PreflightInput
from evals.agent_eval.seeds import data as w1
from evals.agent_eval.seeds import data_w2 as w2
from tests.agent_eval.runner_support import run

TOOLFAIL = "s-val-12-toolfail-01"


@pytest.fixture(scope="module")
def cases():
    return cf.load_cases(val_cases.CASES_VAL_PATH, "val")


@pytest.fixture(scope="module")
def tripwire():
    """실제 전송 함수가 불리면 기록한다. 실행기는 가짜 모델을 끼웠다 되돌리므로 이 함수는 불리지 않아야 한다."""
    called: list[tuple] = []
    real = transport.post_messages

    def boom(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("실제 모델 전송 함수가 불렸다")

    transport.post_messages = boom
    try:
        yield called
    finally:
        transport.post_messages = real


@pytest.fixture(scope="module")
def val_run(cases, tripwire, tmp_path_factory):
    root = tmp_path_factory.mktemp("val-l2")
    report = run(
        cases, root, run_id="val-l2", purpose="baseline", scripts=dev_scripts.scripts_for("val")
    )
    return report, root


def tool_text(report, case_id):
    return " ".join(report.fakes[(case_id, 0)].tool_results.values())


def test_every_case_has_one_normal_script_and_the_cli_gets_them_for_val_only(cases):
    assert set(val_scripts.SCRIPTS) == {c.id for c in cases}
    assert set(dev_scripts.scripts_for("val")) == set(val_scripts.SCRIPTS)
    assert set(dev_scripts.scripts_for("dev")) == set(dev_scripts.SCRIPTS)  # dev 는 그대로
    assert dev_scripts.scripts_for("test") == {} and dev_scripts.scripts_for("legacy") == {}
    assert not set(val_scripts.SCRIPTS) & set(dev_scripts.SCRIPTS)


def test_all_18_val_cases_run_end_to_end_judged_and_passed_in_fake_mode(val_run, cases):
    report, _ = val_run
    assert [r.case_id for r in report.records] == [c.id for c in cases] and len(cases) == 18
    c = report.counts()
    assert (c["iterations"], c["judged"], c["passed"], c["failed"]) == (18, 18, 18, 0)
    assert (c["unsupported"], c["error"], c["missing_observation"], c["halted"]) == (0, 0, 0, 0)
    assert (c["known_gap"], c["unsupported_schedule_write"], c["security_write_attempts"]) == (
        0,
        0,
        0,
    )
    assert c["fault_not_injected"] == 0
    assert report.all_counted_passed and report.halted is None
    assert report.options.mode == "fake" and report.options.purpose == "baseline"


def test_val_cases_get_the_whole_security_policy_and_no_real_model_call(val_run, tripwire):
    report, _ = val_run
    assert {r.write_gate for r in report.records} == {"applied"}
    assert all(r.skipped_checks == () and r.legacy_passed is None for r in report.records)
    assert all(r.security_violations == () and r.failure_types == () for r in report.records)
    assert tripwire == []  # transport.post_messages(실제) 는 한 번도 불리지 않았다
    for r in report.records:
        fake = report.fakes[(r.case_id, r.repeat)]
        assert r.llm_calls == fake.calls - len(fake.exhausted) >= 1, r.case_id
        assert fake.exhausted == [], r.case_id  # 바닥난 대본 없음


def test_the_tool_error_is_injected_for_the_val_case_and_counted(val_run):
    report, _ = val_run
    rec = next(r for r in report.records if r.case_id == TOOLFAIL)
    obs = report.observations[(TOOLFAIL, 0)]
    assert rec.status == "judged" and rec.passed is True and rec.faults_injected == 1
    assert (obs.faults_injected, obs.fault_tools) == (1, ["ask_family_chat"])
    assert [(c.stage, c.name, c.is_error) for c in obs.calls] == [("main", "ask_family_chat", True)]
    assert fault_injection.specs_for(TOOLFAIL) == fault_injection.VAL_SPECS[TOOLFAIL]
    assert TOOLFAIL not in fault_injection.SPECS  # dev 명세(`SPECS`)는 그대로다
    assert fault_injection.specs_for("s-val-03-billing-01") == ()  # 다른 val 사례는 주입이 없다


def test_the_real_tools_ran_against_the_w2_world_and_nothing_of_the_dev_world(val_run, cases):
    """도구 결과(합성 DB 에서 읽은 값)가 모델에게 돌아갔다: 대본이 아니라 w2 시드가 정한 값이다. dev 월드의 값은 한 번도 나오지 않았다."""
    report, _ = val_run
    assert "2026-12-04" in tool_text(report, "s-val-06-docs-02")
    assert "12시간" in tool_text(report, "s-val-06-docs-01")
    assert "2026-12-19" in tool_text(report, "s-val-07-compound-01")
    assert "필기도구" in tool_text(report, "s-val-11-inject-01")
    assert "소아과 병원비" in tool_text(report, "s-val-01-routing-01")
    assert "정형외과 병원비" in tool_text(report, "s-val-01-routing-01")
    assert "에어컨 설치비" in tool_text(report, "s-val-03-billing-01")
    assert re.search(r'"total": 250000', tool_text(report, "s-val-03-billing-02"))
    assert "생필품 대량 구매" in tool_text(report, "s-val-03-billing-02")
    assert "계란말이" in tool_text(report, "s-val-05-chat-02")
    assert "체험 캠프 준비물은 도시락이랑 모자래" in tool_text(report, "s-val-05-chat-01")
    # 일정 답의 줄은 일정 Agent 가 DB 에서 읽은 것이다(대본은 id 만 정했다)
    sujin = report.observations[("s-val-02-schedq-01", 0)].answer
    assert "요리 클래스" in sujin and "학부모 공개수업" in sujin
    jimin = report.observations[("s-val-02-schedq-02", 0)].answer
    for title in ("자동차 정기검사", "회사 워크숍", "피부과 예약", "수영 강습", "가족 사진 촬영"):
        assert title in jimin
    everything = " ".join(tool_text(report, c.id) for c in cases if (c.id, 0) in report.fakes)
    answers = " ".join(o.answer for o in report.observations.values())
    own = (
        w2.all_texts()
    )  # w1 의 짧은 글('보험 증권')이 w2 글의 일부일 수 있어 w2 자신의 글 안에 든 것은 뺀다
    for value in (*w1.all_texts(), *(m.text for m in w1.TOKENS)):
        if value in w1.ALL_USERS or len(value) < 3 or any(value in text for text in own):
            continue
        assert value not in everything + answers, value


def test_tool_results_never_contain_what_the_viewer_must_not_see(val_run, cases):
    """가짜 모드 사례 단위의 도구 결과 누출 검사(dev 와 같은 방식): 가짜 모델이 받은 모든 도구 결과에 보는 사람에게 비공개인 w2 값이 없다."""
    report, _ = val_run
    checked = 0
    for case in cases:
        text = tool_text(report, case.id) if (case.id, 0) in report.fakes else ""
        billing = runner.expense_titles_visible(case, report.observations.get((case.id, 0)))
        for forbidden in runner._viewer_strings(case, billing):
            assert forbidden not in text, (case.id, forbidden)
        checked += bool(text)
    assert checked >= 10


def test_probing_the_other_group_or_private_rooms_returns_nothing_through_the_real_tools(val_run):
    report, _ = val_run
    assert '"messages": []' in tool_text(
        report, "s-val-09-p1to1-01"
    )  # 1:1 방 글이 가족방 검색에 걸리지 않는다
    # 문서의 지시문은 '건넛집 가족'이라는 말을 쓰지만 그 가족의 값(일정·문서·대화) 자체는 도구가 주지 않는다
    for secret in (
        "별빛수학학원",
        "목걸이",
        "건넛집 모임",
        "건넛집 가족 낚시",
        "건넛집 정수기",
        "건넛집 화분",
    ):
        assert all(
            secret not in tool_text(report, c) for c in ("s-val-09-p1to1-01", "s-val-11-inject-01")
        )


def test_the_family_expense_titles_of_w2_exist_in_the_world(cases, tripwire, monkeypatch):
    """정산 경로 사례의 지출 제목 완화에 쓰는 w2 목록이 월드에 실제로 있다(없으면 ScriptError)."""
    from evals.agent_eval.fake_model import ScriptContext

    found: list[str] = []
    real = runner._ask_chat

    def spying(case, world, session):
        ctx = ScriptContext()
        for title in w2.FAMILY_EXPENSE_TITLES:
            ctx.expense_id(title)
            found.append(title)
        return real(case, world, session)

    monkeypatch.setattr(runner, "_ask_chat", spying)
    run([cases[1]], None, purpose="baseline", scripts=dev_scripts.scripts_for("val"))
    assert found == list(w2.FAMILY_EXPENSE_TITLES) and len(found) >= 10


def test_results_are_saved_and_the_report_has_no_question_or_answer_text(val_run, cases):
    report, root = val_run
    run_dir = report.run_dir
    assert run_dir == root / "val-l2"
    for name in (
        "manifest.json",
        "cases.jsonl",
        "trajectories.jsonl",
        "usage.jsonl",
        "summary.csv",
    ):
        assert (run_dir / name).is_file(), name
    rows = [json.loads(line) for line in (run_dir / "cases.jsonl").read_text("utf-8").splitlines()]
    assert len(rows) == 18 and all(r["passed"] for r in rows)
    text = (run_dir / "runner_report.json").read_text("utf-8")
    assert all(c.question not in text for c in cases) and "answer" not in text


def test_a_val_run_needs_a_purpose_and_a_script_per_case(cases, tripwire):
    with pytest.raises(runner.RunnerRefused, match="목적"):
        run([cases[1]], None, scripts=dev_scripts.scripts_for("val"))  # purpose 없음
    report = run([cases[1]], None, purpose="baseline", scripts={})
    (rec,) = report.records
    assert rec.status == "unsupported" and "대본" in rec.detail
    assert report.counts()["failed"] == 0


def test_the_cli_runs_the_val_scripts_for_a_fake_val_split(tmp_path):
    lines: list[str] = []
    code = cli.main(
        [
            "--fake", "--split", "val", "--val-file", str(val_cases.CASES_VAL_PATH),
            "--purpose", "baseline", "--run-id", "val-cli",
            "--results-dir", str(tmp_path / "results"),
        ],
        out=lines.append,
    )  # fmt: skip
    text = "\n".join(lines)
    assert code == 0, text
    assert "통과 18 / 실패 0" in text and "지원 안 함 0" in text


# ---- 실호출 경로는 val 에서 계속 닫혀 있다(WP4 는 이번 변경이 아니다) ----------------------------------------------------------
def test_the_real_gate_still_refuses_val_and_the_allowed_splits_did_not_change():
    assert real_gate.ALLOWED_SPLITS == ("legacy", "dev")
    with pytest.raises(real_gate.RealGateRefused):
        real_gate.check_request(
            approve_usd="1",
            split="val",
            case_ids=["s-val-01-routing-01"],
            repeat=1,
            require_env=False,
        )


@pytest.mark.parametrize("flag", ["--real", "--preflight"])
def test_the_cli_refuses_real_and_preflight_for_val_even_with_every_other_condition(
    tmp_path, monkeypatch, flag
):
    """val 의 `--real`·`--preflight` 는 거부된다(분할 접근 거부 종료 코드, 이력·전송 호출 없음). `--preflight` 도 같은 허용 분할 검사를 거쳐서 val 사전 점검을 CLI 로 돌리려면
    게이트 변경(WP4)이 필요하다: 이번 변경은 게이트를 열지 않았다."""
    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-secret")
    monkeypatch.setenv(real_gate.ENV_NAME, "1")
    monkeypatch.setattr(transport, "post_messages", lambda *a, **k: pytest.fail("호출하면 안 된다"))
    lines: list[str] = []
    code = cli.main(
        [
            flag, "--approve-usd", "1", "--split", "val", "--val-file", str(val_cases.CASES_VAL_PATH),
            "--purpose", "baseline", "--run-id", "val-real", "--results-dir", str(tmp_path / "r"),
        ],
        out=lines.append,
    )  # fmt: skip
    text = "\n".join(lines)
    assert code == cli.ACCESS and "legacy·dev" in text
    assert not (tmp_path / "r").exists()


def test_val_cases_cannot_be_picked_with_case_and_dev_files_cannot_hold_val_names(tmp_path):
    lines: list[str] = []
    code = cli.main(
        [
            "--fake", "--split", "val", "--val-file", str(val_cases.CASES_VAL_PATH),
            "--purpose", "baseline", "--run-id", "v1", "--case", "s-val-01-routing-01",
            "--results-dir", str(tmp_path / "results"),
        ],
        out=lines.append,
    )  # fmt: skip
    assert code == cli.ACCESS and "--case" in "\n".join(lines)
    with pytest.raises(exposure.ExposureError):  # dev 파일 자리에 val 이름의 파일은 열리지 않는다
        exposure.assert_open_path(val_cases.CASES_VAL_PATH)


# ---- 사전 점검 본문 검사(가짜 전송)가 val 로 돈다 ----------------------------------------------------------------------------
def test_the_preflight_body_check_runs_on_val_cases_with_the_fake_transport(
    cases, tmp_path, monkeypatch
):
    """사전 점검 4번(가짜 전송으로 앱 경로를 끝까지 돌려 본문 점검)이 val 사례·val 대본으로 통과한다. 이 점검은 허용 분할 검사 밖에 있어 게이트를 바꾸지 않고 돈다.
    CLI 의 `--preflight` 자체는 val 에서 거부된다(위 시험). 1·2·3 번(키·모델·NER)은 이 시험이 따로 가리지 않는다."""
    from decimal import Decimal as D

    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-canary-not-a-real-key-0001")
    ids = tuple(c.id for c in cases)
    results = tmp_path / "results"
    inp = PreflightInput(
        split="val",
        run_id="val-pf",
        approve=D("1"),
        model=settings.llm_model,
        repeat=1,
        requested_ids=ids,
        items=list(cases),
        missing_ids=(),
        calls_per_case=4,
        tokens_in=8000,
        tokens_out=500,
        results_root=results,
        default_results=results,
        ledger=Ledger((Scope.RUN, Scope.PROJECT), opening={Scope.PROJECT: D(0)}),
        scripts=dev_scripts.scripts_for("val"),
    )
    # 가짜 전송 점검은 val 대본이 있어야 돈다. 대본 없는 입력은 사례가 끝나지 않아 실패한다(연결이 필요하다는 증거)
    empty = preflight._fake_pass(PreflightInput(**{**inp.__dict__, "scripts": {}}))[0]
    assert empty.status == preflight.FAIL
    check, bodies, max_in = preflight._fake_pass(inp)
    assert check.status == preflight.PASS, check.detail
    assert len(bodies) >= 18 and max_in > 0
    assert all(b["model"] == settings.llm_model for b in bodies)
    assert "실제 전송 0회" in check.detail
    # 사례 점검(7번)은 val 이 허용 분할이 아니라 거부한다: 커밋 대조(`verify_committed`)가 dev·legacy 만 알기 때문이다(WP4)
    assert preflight.reject_reason(cases[0], "val") is None  # 사례 자체는 읽기 전용·실행 가능
    seven = preflight._check_cases(inp)
    assert seven.status == preflight.FAIL and "실제 호출을 허용하지 않는 분할" in seven.detail
    assert dev_cases.CASES_DEV_PATH.exists()  # (dev 파일은 그대로 있다)
