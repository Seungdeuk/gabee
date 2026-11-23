"""일반화 평가 사례 5건의 제한적 실호출 허용 시험(L0, 실제 호출 0회).

허용: 커밋된 `cases_gen_isolation.json` 의 사례 5건만(경로·id·내용 해시·고정값 일치). 공식 dev 36건의 허용 규칙은 그대로이고,
위장·변조·미커밋·허용 목록 밖 사례와 val·test·all 의 실호출은 계속 거부한다. 같은 검증을 사전 점검(7번)과 실제 실행(러너) 양쪽이 쓴다.

주의: 커밋 대조(`_require_head_clean`)는 파일이 HEAD 와 같아야 하므로 이 시험은 사례·고정값 파일이 커밋된 뒤에 통과한다(미커밋이면 거부가 정상 동작이다).
"""

import json
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.agent_eval import case_files, cli, dev_cases, gen_cases, preflight, real_gate, runner
from evals.agent_eval.real_gate import real_grant_scope
from evals.agent_eval.runner import RunnerRefused, RunOptions
from tests.agent_eval.runner_support import new_case, real_grant_for

OFFICIAL = dev_cases.CASES_DEV_PATH
GEN = gen_cases.GEN_PATH


@pytest.fixture(scope="module")
def gen_items():
    return case_files.load_cases(GEN, "dev")


@pytest.fixture(scope="module")
def official_items():
    return case_files.load_cases(OFFICIAL, "dev")


# ---------- 허용 ----------
def test_the_five_committed_generalization_cases_are_accepted(gen_items):
    assert len(gen_items) == 5
    runner.verify_committed(gen_items, "dev")
    runner.verify_dev_source(GEN, gen_items)
    assert set(runner.committed_gen_rows()) == {c.id for c in gen_items}


def test_a_real_grant_for_the_generalization_cases_passes_the_runner_gate(gen_items):
    """실제 실행 쪽 검증: 허가가 있고 사례가 커밋된 일반화 사례와 같으면 러너의 허가 확인을 통과한다(호출은 하지 않는다)."""
    ids = [c.id for c in gen_items]
    options = RunOptions("r", mode="real", approved_usd=D("1"))
    with real_grant_scope(real_grant_for(gen_items)):
        grant = runner._check_real_grant(gen_items, gen_items, ids, options)
    assert grant is not None


def test_the_preflight_case_check_accepts_them_and_uses_the_same_rule(gen_items):
    ids = tuple(c.id for c in gen_items)
    inp = SimpleNamespace(
        missing_ids=(), requested_ids=ids, items=gen_items, split="dev", source_file=GEN
    )
    check = preflight._check_cases(inp)
    assert check.no == 7 and check.status == preflight.PASS, check.detail


# ---------- 공식 dev 는 그대로 ----------
def test_official_dev_cases_are_still_accepted_without_touching_the_generalization_files(
    official_items, monkeypatch
):
    def never(*a, **k):
        raise AssertionError("공식 dev 검증이 일반화 파일을 읽었다")

    monkeypatch.setattr(runner, "committed_gen_rows", never)
    runner.verify_committed(official_items, "dev")
    runner.verify_dev_source(OFFICIAL, official_items)
    assert len(official_items) == 36


def test_the_official_and_generalization_id_sets_are_disjoint(gen_items, official_items):
    assert not {c.id for c in gen_items} & {c.id for c in official_items}


# ---------- 거부 ----------
def test_a_tampered_generalization_case_is_refused(gen_items):
    changed = gen_items[0].model_copy(update={"question": gen_items[0].question + " (바꿈)"})
    with pytest.raises(RunnerRefused, match="다르다"):
        runner.verify_committed([changed, *gen_items[1:]], "dev")
    with real_grant_scope(real_grant_for([changed])):
        with pytest.raises(RunnerRefused, match="다르다"):
            runner._check_real_grant(
                [changed],
                [changed],
                [changed.id],
                RunOptions("r", mode="real", approved_usd=D("1")),
            )


def test_a_case_outside_the_allow_list_is_refused(gen_items):
    outside = new_case("s-gen-01-mixed-99", split="dev")
    with pytest.raises(RunnerRefused, match="목록에 없는"):
        runner.verify_committed([outside], "dev")
    stranger = new_case("s-other-01", split="dev")
    with pytest.raises(RunnerRefused, match="목록에 없는"):
        runner.verify_committed([stranger], "dev")


def test_an_uncommitted_or_modified_generalization_file_is_refused(gen_items, monkeypatch):
    def dirty(paths):
        raise RunnerRefused("기준 사례 파일이 HEAD 커밋과 다르다(미커밋)")

    monkeypatch.setattr(runner, "_require_head_clean", dirty)
    with pytest.raises(RunnerRefused, match="HEAD"):
        runner.verify_committed(gen_items, "dev")


def test_pin_mismatches_are_refused(tmp_path):
    rows = json.loads(GEN.read_text("utf-8"))
    pins = json.loads(gen_cases.PINS_PATH.read_text("utf-8"))
    cases_file = tmp_path / "cases.json"
    pins_file = tmp_path / "pins.json"

    def run(rows_, pins_):
        cases_file.write_text(json.dumps(rows_, ensure_ascii=False, indent=1) + "\n", "utf-8")
        pins_file.write_text(json.dumps(pins_, ensure_ascii=False, indent=1) + "\n", "utf-8")
        return gen_cases.check_pins(cases_file, pins_file)

    assert run(rows, pins) == []  # 같은 내용은 일치
    edited = json.loads(json.dumps(rows))
    edited[0]["question"] += " 바꿈"
    assert any("해시" in p for p in run(edited, pins))
    assert any("동결" in p for p in run(rows, {**pins, "frozen_before_any_model_output": False}))
    assert any("사례 수" in p for p in run(rows[:4], pins))
    wrong = json.loads(json.dumps(pins))
    wrong["cases"][2]["case_sha256"] = "0" * 64
    assert any("해시" in p for p in run(rows, wrong))
    # 해시를 파일에 맞춰 같이 바꿔도(고정값까지 바꿈) 코드의 사례 정의와 다르면 거부한다
    forged_rows = json.loads(json.dumps(rows))
    forged_rows[1]["expect"]["answer"]["contains_any"] = [["아무거나"]]
    forged_pins = json.loads(json.dumps(pins))
    forged_pins["cases_file_sha256"] = gen_cases.file_sha256(
        (json.dumps(forged_rows, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    )
    forged_pins["cases"][1]["case_sha256"] = gen_cases.case_sha256(forged_rows[1])
    assert any("정의" in p for p in run(forged_rows, forged_pins))


def test_the_gate_refuses_when_the_pins_do_not_match(gen_items, monkeypatch):
    monkeypatch.setattr(
        gen_cases, "check_pins", lambda *a, **k: ["사례 파일 해시가 고정값과 다르다"]
    )
    with pytest.raises(RunnerRefused, match="고정값"):
        runner.verify_committed(gen_items, "dev")


def test_a_disguised_dev_file_or_wrong_path_is_refused(gen_items, official_items, tmp_path):
    copy = tmp_path / "cases_dev_copy.json"
    copy.write_bytes(GEN.read_bytes())
    with pytest.raises(RunnerRefused, match="허용된 사례 파일"):
        runner.verify_dev_source(copy, gen_items)  # 같은 내용의 다른 경로
    with pytest.raises(RunnerRefused, match="허용된 사례 파일"):
        runner.verify_dev_source(OFFICIAL, gen_items)  # 공식 dev 파일 경로에 일반화 사례
    with pytest.raises(RunnerRefused, match="사례 파일에는 일반화 사례"):
        runner.verify_dev_source(GEN, [*gen_items, official_items[0]])  # 일반화 파일에 공식 사례
    check = preflight._check_cases(
        SimpleNamespace(
            missing_ids=(),
            requested_ids=tuple(c.id for c in gen_items),
            items=gen_items,
            split="dev",
            source_file=copy,
        )
    )
    assert check.status == preflight.FAIL and "허용된 사례 파일" in check.detail


# ---------- 실제 CLI 실행 경로: 허용되지 않은 --dev-file 은 허가 발급·네트워크 호출 전에 거부 ----------
def _real_args(dev_file, split="dev"):
    return cli.build_parser().parse_args(
        [
            "--real",
            "--approve-usd",
            "0.2",
            "--split",
            split,
            "--dev-file",
            str(dev_file),
            "--repeat",
            "3",
            *[a for i in range(1, 6) for a in ("--case", f"s-gen-01-mixed-0{i}")],
        ]
    )


@pytest.fixture
def no_network(monkeypatch):
    """실제 호출·허가 발급이 한 번이라도 일어나면 시험을 실패시킨다."""
    import httpx

    from app.shared.config import settings
    from app.shared.llm import transport

    monkeypatch.setenv(real_gate.ENV_NAME, "1")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-canary-gen-gate-0001")
    sent: list[str] = []

    def boom(*a, **k):
        sent.append("call")
        raise AssertionError("실제 호출을 시도했다")

    def no_grant(*a, **k):
        sent.append("grant")
        raise AssertionError("허가가 발급됐다")

    monkeypatch.setattr(httpx, "post", boom)
    monkeypatch.setattr(httpx.Client, "send", boom)
    monkeypatch.setattr(transport, "post_messages", boom)
    monkeypatch.setattr(real_gate, "issue_grant", no_grant)
    return sent


def test_the_cli_execute_path_refuses_a_disallowed_dev_file_before_any_grant_or_call(
    tmp_path, no_network, monkeypatch
):
    """`_execute` 자체의 검사(사전 점검을 거치지 않은 호출에도 적용): 같은 내용의 다른 경로는 허가 발급 전에 거부한다."""
    copy = tmp_path / "cases_dev_copy.json"
    copy.write_bytes(GEN.read_bytes())
    args = _real_args(copy)
    plan = cli.make_plan(args)
    messages: list[str] = []
    code = cli._execute(args, plan, messages.append)
    assert code == cli.REFUSED
    assert any("허용된 사례 파일" in m for m in messages), messages
    assert no_network == []  # 허가 발급도, 모델 호출도 없었다


def test_the_full_real_cli_stops_at_the_preflight_for_a_disallowed_dev_file(tmp_path, no_network):
    """`--real` 전체 경로: 사전 점검 7번이 거부하고 실행(허가 발급)에는 들어가지 않는다."""
    copy = tmp_path / "cases_dev_copy.json"
    copy.write_bytes(GEN.read_bytes())
    lines: list[str] = []
    code = cli.main(
        [
            "--real",
            "--approve-usd",
            "0.2",
            "--split",
            "dev",
            "--dev-file",
            str(copy),
            "--repeat",
            "3",
            *[a for i in range(1, 6) for a in ("--case", f"s-gen-01-mixed-0{i}")],
        ],
        out=lines.append,
    )
    assert code != cli.OK
    assert any("허용된 사례 파일" in line for line in lines)
    assert no_network == []


def test_the_runner_checks_case_content_and_the_cli_checks_the_file_path(gen_items, tmp_path):
    """역할 구분: 러너(`_check_real_grant`)는 파일 경로를 모르므로 사례 **내용**만 대조하고, 경로는 CLI(`verify_dev_source`)가 맡는다.
    같은 내용이면 러너는 경로와 무관하게 통과하므로 경로 검사가 CLI 쪽에 반드시 있어야 한다는 것을 고정한다."""
    ids = [c.id for c in gen_items]
    options = RunOptions("r", mode="real", approved_usd=D("1"))
    with real_grant_scope(real_grant_for(gen_items)):
        assert runner._check_real_grant(gen_items, gen_items, ids, options) is not None
    copy = tmp_path / "other_path.json"
    copy.write_bytes(GEN.read_bytes())
    with pytest.raises(RunnerRefused, match="허용된 사례 파일"):
        runner.verify_dev_source(copy, gen_items)


# ---------- val·test·all 은 계속 금지, 한도 불변 ----------
@pytest.mark.parametrize("split", ["val", "test", "all"])
def test_val_test_all_real_calls_stay_forbidden_even_with_the_generalization_file(split):
    assert real_gate.ALLOWED_SPLITS == ("legacy", "dev")
    args = cli.build_parser().parse_args(
        [
            "--real",
            "--approve-usd",
            "0.2",
            "--split",
            split,
            "--dev-file",
            str(GEN),
            "--case",
            "s-gen-01-mixed-01",
        ]
    )
    with pytest.raises(cli.Refusal):
        cli.make_plan(args)
    with pytest.raises(RunnerRefused):
        runner.committed_rows(split)


def test_case_count_repeat_and_cost_limits_are_unchanged():
    ids = [f"s-gen-01-mixed-0{i}" for i in range(1, 6)]
    # 5건 x 반복 3 은 기존 한도 안이다
    real_gate.check_request(
        approve_usd=D("0.2"), split="dev", case_ids=ids, repeat=3, require_env=False
    )
    with pytest.raises(real_gate.RealGateRefused):  # 반복 상한(3)은 그대로
        real_gate.check_request(
            approve_usd=D("0.2"), split="dev", case_ids=ids, repeat=4, require_env=False
        )
    with pytest.raises(real_gate.RealGateRefused):  # 명시한 사례 수 상한(10)은 그대로
        real_gate.check_request(
            approve_usd=D("0.2"),
            split="dev",
            case_ids=[f"x-{i}" for i in range(11)],
            repeat=1,
            require_env=False,
        )
    with pytest.raises(real_gate.RealGateRefused):  # 사례를 명시하지 않은 호출은 그대로 거부
        real_gate.check_request(
            approve_usd=D("0.2"), split="dev", case_ids=[], repeat=1, require_env=False
        )


def test_gen_case_file_is_not_a_hidden_val_or_test_path():
    assert Path(GEN).name == "cases_gen_isolation.json"
    assert "val" not in GEN.stem and "test" not in GEN.stem
