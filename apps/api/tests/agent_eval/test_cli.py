"""CLI 시험(L0): 기본은 --dry-run, --real 은 승인 조건, 분할 접근 조건. 실제 모델·네트워크는 부르지 않는다.

`--real` 의 "승인 조건을 통과한 뒤 실행"은 전송 함수를 가짜로 바꿔 둔 상태에서만 다룬다(실제 API 키·네트워크를 쓰는 시험은 없다).
"""

import json
from decimal import Decimal as D

import pytest

from app.shared.llm import transport
from evals.agent_eval import (
    adapter,
    cli,
    estimate,
    fake_model,
    preflight,
    real_gate,
    runs_guard,
    store,
)
from evals.agent_eval.adapter import load_legacy_cases
from evals.agent_eval.cost import Ledger
from tests.agent_eval.runner_support import legacy, new_case

LEGACY_COUNT = len(
    load_legacy_cases()
)  # 기존 사례 파일의 사례 수(사례를 더해도 시험이 깨지지 않게 파일에서 읽는다)
LEGACY_ESTIMATE = (
    f"{D('0.00105') * LEGACY_COUNT * 4:.5f} USD"  # N x 1 x 4 호출, 호출당 8000/500 토큰, Haiku 5.5
)


def main(argv, tmp_path):
    lines: list[str] = []
    code = cli.main([*argv, "--results-dir", str(tmp_path / "results")], out=lines.append)
    return code, "\n".join(lines)


@pytest.fixture(autouse=True)
def real_allowed(monkeypatch, tmp_path):
    """`--real` 은 기본으로 막혀 있고 환경변수·`--approve-usd`·`--case` 가 모두 있어야 열린다. 승인·예산 조건 시험은 전송 함수를 가짜로 바꾼 상태에서만 연다.

    환경변수를 켜 두고(`real_gate.ENV_NAME`), 기본 결과 폴더를 시험 임시 폴더로 바꾼다(실제 결과 폴더에는 쓰지 않는다). NER 필수 모드 점검은 이 PC 의 모델 폴더에
    달려 있어서 여기서는 통과로 둔다(그 점검 자체는 `test_preflight.py` 가 별도로 시험한다)."""
    monkeypatch.setenv(real_gate.ENV_NAME, "1")
    monkeypatch.setattr(cli, "DEFAULT_RESULTS", tmp_path / "results")
    monkeypatch.setattr(cli, "DEFAULT_FAKE_RESULTS", tmp_path / "results" / "_fake")
    monkeypatch.setattr(preflight, "ner_probe", lambda: (True, "시험용 통과"))


@pytest.fixture
def untouchable(monkeypatch):
    """환경 준비·전송·`runner` 실행이 불리면 시험을 실패시킨다(거부·추정 경로는 아무것도 부르지 않는다)."""
    called = []

    def boom(*a, **k):
        called.append(1)
        raise AssertionError("불리면 안 되는 함수가 불렸다")

    monkeypatch.setattr(cli, "prepare_environment", boom)
    monkeypatch.setattr(cli, "_execute", boom)
    monkeypatch.setattr(transport, "post_messages", boom)
    return called


def test_the_default_is_a_dry_run_that_prints_the_estimate_and_calls_nothing(tmp_path, untouchable):
    code, text = main([], tmp_path)
    assert code == 0 and untouchable == []
    assert f"사례 {LEGACY_COUNT} x 반복 1 x 사례당 최대 4회 = 호출 {LEGACY_COUNT * 4}회" in text
    assert LEGACY_ESTIMATE in text
    assert "가정: 호출당 입력 8000 / 출력 500 토큰" in text
    assert "아무것도 저장하지 않았다" in text
    assert not (tmp_path / "results").exists()  # 결과 폴더도 만들지 않았다


def test_the_dry_run_estimate_matches_the_estimate_module_and_follows_the_options(
    tmp_path, untouchable
):
    code, text = main(
        [
            "--dry-run",
            "--case",
            "b-total",
            "--case",
            "m-billing",
            "--repeat",
            "3",
            "--calls-per-case",
            "5",
            "--tokens-in",
            "9000",
            "--tokens-out",
            "600",
        ],
        tmp_path,
    )
    expected, _ = estimate.build_estimate(
        Ledger((cli.Scope.RUN,)), "claude-haiku-5-5", 2, 3, 5, 9000, 600
    )
    assert code == 0 and "사례 2 x 반복 3 x 사례당 최대 5회 = 호출 30회" in text
    assert f"추정 비용: {format(expected, 'f')} USD" in text


@pytest.mark.parametrize(
    "argv",
    [
        ["--real"],
        ["--fake", "--real", "--approve-usd", "1"],
        ["--dry-run", "--fake"],
        ["--dry-run", "--real", "--approve-usd", "1"],
        ["--approve-usd", "1"],
        ["--fake", "--approve-usd", "1"],
        ["--real", "--approve-usd", "abc"],
        ["--real", "--approve-usd", "0"],
        ["--real", "--approve-usd", "-3"],
        ["--real", "--approve-usd", "nan"],
        ["--real", "--approve-usd", "inf"],
        ["--real", "--approve-usd", "1"],  # --case 없음: 전체 실행은 없다
        ["--real", "--approve-usd", "1", "--case", "b-total", "--case", "b-total"],
        ["--preflight"],
        ["--preflight", "--real", "--approve-usd", "1", "--case", "b-total"],
        ["--preflight", "--fake"],
    ],
)
def test_unapproved_or_unknown_combinations_are_refused_before_anything_runs(
    argv, tmp_path, untouchable
):
    code, text = main(argv, tmp_path)
    assert code == cli.REFUSED and text.startswith("거부") and untouchable == []


def test_real_is_refused_when_the_estimate_exceeds_the_approved_amount(tmp_path, untouchable):
    code, text = main(
        ["--real", "--approve-usd", "0.001", "--case", "b-total"], tmp_path
    )  # 추정 0.0042 > 0.001
    assert code == cli.OVER_BUDGET and untouchable == []
    assert code not in (0, 1, 2, cli.REFUSED)  # 인자 오류(2)나 다른 거부와 다른 값이다
    assert "거부" in text and "0.001" in text and not (tmp_path / "results").exists()


def test_real_is_refused_when_the_estimate_exceeds_the_global_budget_even_if_approved(
    tmp_path, untouchable
):
    ids = [c.case.id for c in adapter.load_legacy_cases()[:10]]
    # 실호출은 반복 3회까지라 이 크기의 추정은 --real 로 만들 수 없다(반복 상한은 test_real_hardening). 같은 추정 상한 검사는 dry-run 에서 본다
    argv = ["--dry-run", "--repeat", "50"]
    code, text = main(
        [*argv, *[a for i in ids for a in ("--case", i)]], tmp_path
    )  # 2.1달러 > 실행 상한 2달러
    assert code == cli.OVER_BUDGET and "예산 초과" in text and untouchable == []


def test_real_without_an_api_key_is_refused_after_the_gate_and_the_value_is_never_printed(
    tmp_path, monkeypatch
):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(transport, "post_messages", lambda *a, **k: pytest.fail("호출하면 안 된다"))
    code, text = main(["--real", "--approve-usd", "1", "--case", "b-total"], tmp_path)
    assert code == cli.REFUSED and "ANTHROPIC_API_KEY" in text and "[실패]" in text


def test_real_with_a_different_model_than_the_server_setting_is_refused(tmp_path, monkeypatch):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-secret")
    code, text = main(
        ["--real", "--approve-usd", "1", "--case", "b-total", "--model", "claude-sonnet-5-5"],
        tmp_path,
    )
    assert code == cli.REFUSED and "ANTHROPIC_MODEL" in text and "sk-test-secret" not in text


def test_an_approved_real_run_goes_through_the_same_path_with_the_transport_swapped_for_a_fake(
    tmp_path, monkeypatch
):
    """승인 조건을 통과하면 실제 경로로 실행한다. 이 환경에서는 전송 함수를 가짜로 바꿔 둔 상태에서만 돌려 실제 호출은 없다."""
    from app.shared.config import settings

    secret = "sk-test-secret-value-1234"
    monkeypatch.setattr(settings, "anthropic_api_key", secret)
    lc = legacy("b-total")[0]
    fake = fake_model.FakeModel(fake_model.script_for(lc))
    with fake_model.installed(fake):
        code, text = main(
            ["--real", "--approve-usd", "1", "--case", "b-total", "--run-id", "real-1"], tmp_path
        )
    assert code == 0, text
    assert fake.calls == 2  # 실제 모드도 측정기를 거쳐 호출 수를 센다
    assert secret not in text and "승인 금액 1 USD 이하로 실행한다" in text
    run_dir = tmp_path / "results" / "real-1"
    manifest = json.loads((run_dir / "manifest.json").read_text("utf-8"))
    assert (
        manifest["model"] == "claude-haiku-5-5"
        and manifest["calls"] == 2
        and manifest["stage"] == "other"
    )
    saved = (run_dir / "runner_report.json").read_text("utf-8")
    assert json.loads(saved)["mode"] == "real" and secret not in saved
    # 실제 실행은 이전 지출을 이어 받는다(누적 PROJECT)
    assert store.opening_spent(tmp_path / "results", "other")["project"] > 0


def test_an_approved_real_run_stops_before_the_call_that_could_exceed_the_approved_amount(
    tmp_path, monkeypatch
):
    """추정 단계는 건너뛰고(_execute 직접 호출) 실행 중 상한만 본다: 승인 금액을 넘을 수 있는 첫 호출 전에 멈춘다."""
    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-secret")
    fake = fake_model.FakeModel(fake_model.script_for(legacy("b-total")[0]))
    plan = cli.Plan("real", ("legacy",), D("0.0003"), "stop-1", 1, ("b-total",))
    from evals.agent_eval import runner

    digest = runner.case_fingerprint(legacy("b-total"))
    record = real_gate._mint_preflight(
        "stop-1", D("0.0003"), "legacy", frozenset({"b-total"}), D("0.001"), digest, 1
    )
    lines: list[str] = []
    with fake_model.installed(fake):
        code = cli._execute(_real_args(tmp_path), plan, lines.append, record)
    assert code == cli.HALTED and fake.calls == 0
    assert "중단" in "\n".join(lines) or "승인 금액" in "\n".join(lines)


def test_real_is_blocked_by_default_and_every_real_request_without_the_gate_is_refused(
    tmp_path, monkeypatch
):
    monkeypatch.delenv(real_gate.ENV_NAME)  # 기본 상태: 환경변수 없음
    code, text = main(["--real", "--approve-usd", "1", "--case", "b-total"], tmp_path)
    assert (
        code == cli.REFUSED and real_gate.ENV_NAME in text and not (tmp_path / "results").exists()
    )
    # 환경변수가 있어도 사전 점검 기록 없이 `_execute` 를 직접 불러서는 허가가 나오지 않는다(make_plan·사전 점검을 거치지 않은 호출도 막힌다)
    monkeypatch.setenv(real_gate.ENV_NAME, "1")
    plan = cli.Plan("real", ("legacy",), D("1"), "r", 1, ("b-total",))
    lines: list[str] = []
    assert cli._execute(_real_args(tmp_path), plan, lines.append) == cli.REFUSED
    assert "사전 점검" in "\n".join(lines) and not (tmp_path / "results").exists()
    assert real_gate.real_grant() is None


@pytest.mark.parametrize(
    "flag, value",
    [
        ("--calls-per-case", "3"),
        ("--tokens-in", "7999"),
        ("--tokens-out", "499"),
        ("--tokens-in", "1"),
    ],
)
def test_the_estimate_assumptions_cannot_be_lowered_below_the_defaults(
    flag, value, tmp_path, untouchable
):
    code, text = main(["--dry-run", flag, value], tmp_path)
    assert code == cli.USAGE and "낮출 수 없다" in text and untouchable == []
    # 기본값과 같거나 높이는 것은 된다
    code, _ = main(["--dry-run", "--calls-per-case", "4", "--tokens-in", "8001"], tmp_path)
    assert code == 0


def test_a_fake_run_prints_the_summary_and_saves_outside_the_real_totals(tmp_path):
    code, text = main(
        ["--fake", "--case", "b-total", "--case", "b-write-propose", "--run-id", "fake-1"], tmp_path
    )
    assert code == 0, text
    assert (
        "통과 2 / 실패 0" in text and "쓰기 게이트 미평가 2건" in text and "legacy_passed" in text
    )
    assert (tmp_path / "results" / "fake-1" / "runner_report.json").is_file()
    # 기본 위치의 설계: 가짜 실행 결과는 실제 누적을 읽는 깊이에 두지 않는다
    assert cli.DEFAULT_FAKE_RESULTS.parent == cli.DEFAULT_RESULTS
    nested = tmp_path / "root" / "_fake" / "r1"
    nested.mkdir(parents=True)
    (nested / "manifest.json").write_text(json.dumps({"cost_usd": "9", "stage": "other"}), "utf-8")
    assert store.opening_spent(tmp_path / "root", "other")["project"] == D(0)


def test_a_failing_case_gives_exit_code_one(tmp_path, monkeypatch):
    monkeypatch.setitem(
        fake_model.LEGACY_SCRIPT_OVERRIDES, "b-total", {"billing": [fake_model.say("몰라요")]}
    )
    code, text = main(["--fake", "--case", "b-total", "--run-id", "fail-1"], tmp_path)
    assert code == cli.FAILED and "통과 0 / 실패 1" in text


def test_unknown_case_ids_are_a_usage_error(tmp_path, untouchable):
    code, text = main(["--case", "nope"], tmp_path)
    assert code == cli.USAGE and "nope" in text


# ---------- 분할 접근 ----------
def _cases_file(path, *cases):
    path.write_text(json.dumps([c.model_dump(mode="json") for c in cases]), encoding="utf-8")
    return str(path)


def test_val_and_test_and_all_are_refused_without_a_purpose_and_a_run_id(tmp_path, untouchable):
    for split in ("val", "test", "all"):
        code, text = main(["--split", split], tmp_path)
        assert code == cli.ACCESS and "--run-id" in text and "--purpose" in text
    val = _cases_file(tmp_path / "v.json", new_case("v-1", split="val"))
    assert main(["--split", "val", "--val-file", val, "--run-id", "v1"], tmp_path)[0] == cli.ACCESS
    assert (
        main(["--split", "val", "--run-id", "v1", "--purpose", "baseline"], tmp_path)[0]
        == cli.ACCESS
    )  # 파일 없음
    assert untouchable == []


def test_cases_cannot_be_picked_out_of_a_guarded_split(tmp_path, untouchable):
    val = _cases_file(tmp_path / "v.json", new_case("v-1", split="val"))
    code, text = main(
        [
            "--split",
            "val",
            "--val-file",
            val,
            "--run-id",
            "v1",
            "--purpose",
            "baseline",
            "--case",
            "v-1",
        ],
        tmp_path,
    )
    assert code == cli.ACCESS and "--case" in text


def test_the_test_split_is_real_only_and_needs_its_files_and_a_candidate(
    tmp_path, untouchable, monkeypatch
):
    split_file = _cases_file(tmp_path / "t.json", new_case("t-1", split="test"))
    base = ["--split", "test", "--run-id", "t1", "--purpose", "baseline"]
    code, text = main(
        [*base, "--fake", "--split-file", split_file, "--candidate", "abc1234"], tmp_path
    )
    assert code == cli.ACCESS and "--real" in text  # 가짜로 한 번뿐인 예약을 소모하지 않는다
    assert (
        main([*base, "--real", "--approve-usd", "1"], tmp_path)[0] == cli.ACCESS
    )  # 파일·후보 없음
    assert (
        main(
            [
                *base,
                "--real",
                "--approve-usd",
                "1",
                "--split-file",
                split_file,
                "--candidate",
                "zzz",
            ],
            tmp_path,
        )[0]
        == cli.ACCESS
    )
    assert untouchable == []


def test_a_test_dry_run_only_counts_the_cases_and_does_not_touch_the_history_file(
    tmp_path, monkeypatch, untouchable
):
    split_file = _cases_file(
        tmp_path / "t.json", new_case("t-1", split="test"), new_case("t-2", split="test")
    )
    runs = tmp_path / "test_runs.json"
    runs_guard.init_runs_file(runs)
    monkeypatch.setattr(
        runs_guard, "load_test_cases", lambda *a, **k: pytest.fail("예약하면 안 된다")
    )
    code, text = main(
        [
            "--split",
            "test",
            "--run-id",
            "t1",
            "--purpose",
            "baseline",
            "--split-file",
            split_file,
            "--candidate",
            "abc1234",
            "--runs-file",
            str(runs),
        ],
        tmp_path,
    )
    assert code == 0 and "'test': 2" in text
    assert json.loads(runs.read_text("utf-8"))["runs"] == []


def test_a_real_run_of_val_test_or_all_is_refused_even_with_every_other_condition(
    tmp_path, monkeypatch
):
    """val·test·all 의 실제 호출은 이번 단계에서 금지다. 이력 파일은 예약하지 않는다."""
    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-secret")
    split_file = _cases_file(tmp_path / "t.json", new_case("t-1", split="test"))
    val_file = _cases_file(tmp_path / "v.json", new_case("v-1", split="val"))
    runs = tmp_path / "test_runs.json"
    runs_guard.init_runs_file(runs)
    monkeypatch.setattr(
        runs_guard, "load_test_cases", lambda *a, **k: pytest.fail("예약하면 안 된다")
    )
    monkeypatch.setattr(transport, "post_messages", lambda *a, **k: pytest.fail("호출하면 안 된다"))
    common = [
        "--real",
        "--approve-usd",
        "1",
        "--case",
        "t-1",
        "--purpose",
        "baseline",
        "--run-id",
        "t1",
    ]
    for split in ("test", "val", "all"):
        code, text = main(
            [
                *common, "--split", split, "--split-file", split_file, "--val-file", val_file,
                "--candidate", "abc1234", "--runs-file", str(runs),
            ],
            tmp_path,
        )  # fmt: skip
        assert code == cli.ACCESS and "legacy·dev" in text, split
    assert json.loads(runs.read_text("utf-8"))["runs"] == []
    assert not (tmp_path / "results").exists()


def test_a_dev_dry_run_counts_the_file_and_rejects_cases_of_another_split(tmp_path, untouchable):
    dev = _cases_file(tmp_path / "d.json", new_case("d-1"), new_case("d-2"))
    code, text = main(["--split", "dev", "--dev-file", dev], tmp_path)
    assert code == 0 and "'dev': 2" in text
    mixed = _cases_file(tmp_path / "m.json", new_case("d-1"), new_case("v-1", split="val"))
    assert main(["--split", "dev", "--dev-file", mixed], tmp_path)[0] == cli.ACCESS
    assert main(["--split", "dev"], tmp_path)[0] == cli.ACCESS  # dev 파일이 없으면 시작하지 않는다


def _stub_runner(monkeypatch, tmp_path, spends, halted_at=None):
    """runner.run_cases 를 가짜로 바꿔 분할마다 spends 만큼 쓴 것처럼 보고한다. 받은 승인 금액을 기록해 돌려준다."""
    from types import SimpleNamespace

    from app.shared.config import settings
    from evals.agent_eval import runner

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-secret")
    monkeypatch.setattr(cli, "_load", lambda *a, **k: [])
    seen: list[D | None] = []

    def fake_run(source, options, ledger=None, **_):
        i = len(seen)
        seen.append(options.approved_usd)
        ledger.total = D(spends[i])
        return SimpleNamespace(
            ledger=ledger,
            run_dir=None,
            halted="멈춤" if halted_at == i else "",
            all_counted_passed=True,
            summary_lines=lambda: [],
        )

    monkeypatch.setattr(runner, "run_cases", fake_run)
    return seen


def _real_args(tmp_path):
    return cli.build_parser().parse_args(["--results-dir", str(tmp_path / "results")])


def test_a_multi_split_real_command_is_refused_before_anything_runs(tmp_path, monkeypatch):
    seen = _stub_runner(monkeypatch, tmp_path, ["0.6", "0.6", "0.1"])
    plan = cli.Plan("real", ("legacy", "dev", "val"), D("1"), "r", 1, ("b-total",))
    lines: list[str] = []
    code = cli._execute(_real_args(tmp_path), plan, lines.append)
    assert code == cli.REFUSED and seen == [] and "한 분할만" in "\n".join(lines)


def test_a_budget_halt_in_one_split_stops_the_remaining_splits(tmp_path, monkeypatch):
    seen = _stub_runner(monkeypatch, tmp_path, ["0.1", "0.1", "0.1"], halted_at=0)
    plan = cli.Plan("fake", ("legacy", "dev", "val"), None, "r", 1, ())
    code = cli._execute(_real_args(tmp_path), plan, lambda _: None)
    assert code == cli.HALTED and len(seen) == 1


def test_a_real_run_exhausting_the_approved_amount_stops_before_the_next_call(
    tmp_path, monkeypatch
):
    """실호출 경로(허가 발급 -> run_cases)에서 승인액을 소진하면 다음 호출을 시작하지 않고 종료 코드 7 로 끝난다(가짜 전송)."""
    from app.shared.config import settings
    from evals.agent_eval import runner

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-secret")
    items = legacy("b-total", "m-billing", "b-nov-total", "b-list")
    ids = tuple(i.case.id for i in items)
    fake = fake_model.FakeModel(fake_model.script_for(items[0]))
    plan = cli.Plan("real", ("legacy",), D("0.0015"), "halt-1", 1, ids)
    record = real_gate._mint_preflight(
        "halt-1",
        D("0.0015"),
        "legacy",
        frozenset(ids),
        D("0.01"),
        runner.case_fingerprint(items),
        1,
    )
    lines: list[str] = []
    with fake_model.installed(fake):
        code = cli._execute(_real_args(tmp_path), plan, lines.append, record)
    text = "\n".join(lines)
    assert code == cli.HALTED and "호출 전에 멈춘다" in text
    assert 0 < fake.calls < 9  # 몇 번은 호출했고 나머지는 시작하지 않았다
    spent = sum(
        D(json.loads(line)["cost_usd"])
        for line in (tmp_path / "results" / "halt-1" / "usage.jsonl")
        .read_text("utf-8")
        .splitlines()
    )
    assert 0 < spent <= D("0.0015")  # 승인액을 넘기 전에 멈췄다
    assert real_gate.real_grant() is None
