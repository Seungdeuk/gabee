"""CLI 시험(L0): 기본은 --dry-run, --real 은 승인 조건, 분할 접근 조건. 실제 모델·네트워크는 부르지 않는다.

`--real` 의 "승인 조건을 통과한 뒤 실행"은 전송 함수를 가짜로 바꿔 둔 상태에서만 다룬다(실제 API 키·네트워크를 쓰는 시험은 없다).
"""

import json
from decimal import Decimal as D

import pytest

from app.shared.llm import transport
from evals.agent_eval import cli, estimate, fake_model, runs_guard, store
from evals.agent_eval.cost import Ledger
from tests.agent_eval.runner_support import ask_billing_script, legacy, new_case

LEGACY_52_ESTIMATE = "0.21840 USD"  # 52 x 1 x 4 호출, 호출당 8000/500 토큰, Haiku 5.5


def main(argv, tmp_path):
    lines: list[str] = []
    code = cli.main([*argv, "--results-dir", str(tmp_path / "results")], out=lines.append)
    return code, "\n".join(lines)


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
    assert "사례 52 x 반복 1 x 사례당 최대 4회 = 호출 208회" in text
    assert LEGACY_52_ESTIMATE in text
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
            "1000",
            "--tokens-out",
            "100",
        ],
        tmp_path,
    )
    expected, _ = estimate.build_estimate(
        Ledger((cli.Scope.RUN,)), "claude-haiku-5-5", 2, 3, 5, 1000, 100
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
    ],
)
def test_unapproved_or_unknown_combinations_are_refused_before_anything_runs(
    argv, tmp_path, untouchable
):
    code, text = main(argv, tmp_path)
    assert code == cli.REFUSED and text.startswith("거부") and untouchable == []


def test_real_is_refused_when_the_estimate_exceeds_the_approved_amount(tmp_path, untouchable):
    code, text = main(["--real", "--approve-usd", "0.1"], tmp_path)  # 추정 0.2184 > 0.1
    assert code == cli.OVER_BUDGET and untouchable == []
    assert code not in (0, 1, 2, cli.REFUSED)  # 인자 오류(2)나 다른 거부와 다른 값이다
    assert "거부" in text and "0.1" in text and not (tmp_path / "results").exists()


def test_real_is_refused_when_the_estimate_exceeds_the_global_budget_even_if_approved(
    tmp_path, untouchable
):
    code, text = main(
        ["--real", "--approve-usd", "100", "--repeat", "20"], tmp_path
    )  # 4.4달러 > 실행 상한 2달러
    assert code == cli.OVER_BUDGET and "예산 초과" in text and untouchable == []


def test_real_without_an_api_key_is_refused_after_the_gate_and_the_value_is_never_printed(
    tmp_path, monkeypatch
):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(transport, "post_messages", lambda *a, **k: pytest.fail("호출하면 안 된다"))
    code, text = main(["--real", "--approve-usd", "1", "--case", "b-total"], tmp_path)
    assert code == cli.REFUSED and "ANTHROPIC_API_KEY" in text


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
    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-secret")
    fake = fake_model.FakeModel(fake_model.script_for(legacy("b-total")[0]))
    with fake_model.installed(fake):
        code, text = main(
            [
                "--real",
                "--approve-usd",
                "0.0003",
                "--case",
                "b-total",
                "--calls-per-case",
                "1",
                "--tokens-in",
                "100",
                "--tokens-out",
                "10",
            ],
            tmp_path,
        )
    assert code == cli.HALTED and fake.calls == 0  # 승인 금액을 넘을 수 있는 첫 호출 전에 멈췄다
    assert "중단" in text


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


def test_a_real_test_run_reserves_the_history_and_marks_the_cases_done(tmp_path, monkeypatch):
    from app.shared.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test-secret")
    split_file = _cases_file(tmp_path / "t.json", new_case("t-1", split="test"))
    runs = tmp_path / "test_runs.json"
    runs_guard.init_runs_file(runs)
    fake = fake_model.FakeModel(ask_billing_script())

    def argv(run_id):
        return [
            "--split", "test", "--real", "--approve-usd", "1", "--run-id", run_id,
            "--purpose", "baseline", "--split-file", split_file, "--candidate", "abc1234",
            "--runs-file", str(runs),
        ]  # fmt: skip

    with fake_model.installed(fake):
        code, text = main(argv("t1"), tmp_path)
        assert code == 0, text
        assert runs_guard.status(runs, "t1") == {"t-1": "done"}
        again, text2 = main(argv("t2"), tmp_path)
    assert again == cli.ACCESS and "한 번뿐" in text2  # 같은 목적의 두 번째 평가는 예약되지 않는다
    assert fake.calls == 3


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
    seen: list[D] = []

    def fake_run(source, options, ledger=None):
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


def test_a_multi_split_real_command_shares_one_approved_amount(tmp_path, monkeypatch):
    seen = _stub_runner(monkeypatch, tmp_path, ["0.6", "0.6", "0.1"])
    plan = cli.Plan("real", ("legacy", "dev", "val"), D("1"), "r", 1, ())
    lines: list[str] = []
    code = cli._execute(_real_args(tmp_path), plan, lines.append)
    assert seen == [D("1"), D("0.4")]  # 둘째 분할은 남은 금액만 받는다
    assert code == cli.HALTED and "다 써서" in "\n".join(lines)  # 셋째 분할은 시작하지 않았다


def test_a_budget_halt_in_one_split_stops_the_remaining_splits(tmp_path, monkeypatch):
    seen = _stub_runner(monkeypatch, tmp_path, ["0.1", "0.1", "0.1"], halted_at=0)
    plan = cli.Plan("real", ("legacy", "dev", "val"), D("1"), "r", 1, ())
    code = cli._execute(_real_args(tmp_path), plan, lambda _: None)
    assert code == cli.HALTED and len(seen) == 1
