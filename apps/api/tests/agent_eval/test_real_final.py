"""E7a 마지막 수정 라운드 시험(L0, 실제 호출 0회): 응답 해석 실패 경로의 비용 기록, 기준 사례를 Git HEAD 에서 읽기."""

import subprocess
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.shared.llm import transport
from evals.agent_eval import adapter, preflight, runner, usage
from evals.agent_eval.cost import call_cost
from evals.agent_eval.runner import RunnerRefused, default_ledger
from tests.agent_eval.runner_support import legacy

MODEL = "claude-haiku-5-5"
BODY = {"model": MODEL, "max_tokens": 1024, "messages": [{"role": "user", "content": "안녕"}]}
GOOD = {"model": MODEL, "content": [], "usage": {"input_tokens": 100, "output_tokens": 20}}


def metered(response, *, record_failures=True, mutate=None):
    """가짜 전송 함수가 `response` 를 돌려주도록 두고 측정기를 거쳐 한 번 부른다. (ledger, 돌려받은 값)."""
    ledger = default_ledger("real", D("1"))
    if mutate:
        mutate(ledger)
    original = transport.post_messages
    transport.post_messages = lambda body, **kw: response
    try:
        with usage.meter_llm_calls(ledger, "c", 0, record_failures=record_failures):
            got = transport.post_messages(dict(BODY))
    finally:
        transport.post_messages = original
    return ledger, got


def worst():
    return call_cost(MODEL, usage.estimate_input_tokens(BODY), BODY["max_tokens"])


# ---------- 1. 응답 해석 실패 경로 ----------
def test_a_normal_response_is_recorded_once_as_confirmed():
    ledger, got = metered(GOOD)
    assert got is GOOD and len(ledger.usages) == 1
    (u,) = ledger.usages
    assert not u.unconfirmed and (u.tokens_in, u.tokens_out) == (100, 20)


@pytest.mark.parametrize(
    "response",
    [
        {"model": MODEL, "content": []},  # usage 누락 -> 0/0 무료 호출로 기록되던 경로
        {"model": MODEL, "usage": {}},
        {"model": MODEL, "usage": {"input_tokens": "abc", "output_tokens": 5}},
        {"model": MODEL, "usage": {"input_tokens": "100", "output_tokens": 5}},
        {"model": MODEL, "usage": {"input_tokens": -5, "output_tokens": 5}},
        {"model": MODEL, "usage": {"input_tokens": 10, "output_tokens": None}},
        {"model": MODEL, "usage": {"input_tokens": 10, "output_tokens": 5.5}},
        {"model": MODEL, "usage": {"input_tokens": 0, "output_tokens": 0}},
        {"model": MODEL, "usage": "x"},
        {"model": "claude-unknown-9", "usage": {"input_tokens": 100, "output_tokens": 20}},
        ["응답이 객체가 아니다"],
    ],
)
def test_a_response_whose_usage_or_model_cannot_be_trusted_is_recorded_once_at_the_worst_case(
    response,
):
    ledger, got = metered(response)
    assert got is response  # 앱에는 응답을 그대로 돌려준다(처리는 앱이 한다)
    assert len(ledger.usages) == 1
    (u,) = ledger.usages
    assert u.unconfirmed and u.model == MODEL  # 요청 모델(단가표에 있음)로 기록
    assert u.cost == worst() > 0 and ledger.total == worst()
    assert ledger.remaining()[next(iter(ledger.remaining()))] < D("2")  # 잔여 예산이 줄었다


def test_an_exception_after_the_confirmed_record_does_not_record_again(monkeypatch):
    ledger = default_ledger("real", D("1"))
    real_record = ledger.record

    def record_then_fail(*a, **k):
        real_record(*a, **k)
        raise RuntimeError("확정 기록 직후의 예외")

    ledger.record = record_then_fail
    original = transport.post_messages
    transport.post_messages = lambda body, **kw: GOOD
    try:
        with pytest.raises(RuntimeError, match="직후"):
            with usage.meter_llm_calls(ledger, "c", 0, record_failures=True):
                transport.post_messages(dict(BODY))
    finally:
        transport.post_messages = original
    assert len(ledger.usages) == 1 and not ledger.usages[0].unconfirmed


def test_fake_mode_keeps_the_old_behaviour_for_a_response_without_usage():
    ledger, _ = metered({"model": MODEL, "content": []}, record_failures=False)
    (u,) = ledger.usages
    assert not u.unconfirmed and (u.tokens_in, u.tokens_out) == (0, 0)


def test_a_transport_exception_is_still_recorded_exactly_once():
    ledger = default_ledger("real", D("1"))
    original = transport.post_messages

    def boom(body, **kw):
        raise TimeoutError("응답 없음")

    transport.post_messages = boom
    try:
        with pytest.raises(TimeoutError):
            with usage.meter_llm_calls(ledger, "c", 0, record_failures=True):
                transport.post_messages(dict(BODY))
    finally:
        transport.post_messages = original
    assert len(ledger.usages) == 1 and ledger.usages[0].unconfirmed


# ---------- 2. 기준은 Git HEAD ----------
def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    """임시 git 저장소(실제 저장소는 건드리지 않는다)와 그 안의 커밋된 파일 하나."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    f = root / "cases_dev.json"
    f.write_bytes(
        '[{"id": "x", "question": "질문"}]\n'.encode()
    )  # LF 로 커밋한다(Windows write_text 는 CRLF 가 된다)
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "init")
    return root, f


def test_a_clean_file_passes_and_a_modified_or_uncommitted_file_is_refused(repo):
    root, f = repo
    runner._require_head_clean([f])  # 수정하지 않은 상태는 통과
    f.write_text('[{"id": "x", "question": "바꾼 질문"}]\n', encoding="utf-8")
    with pytest.raises(RunnerRefused, match="HEAD"):
        runner._require_head_clean([f])
    git(root, "checkout", "--", "cases_dev.json")
    new = root / "new_cases.json"
    new.write_text("[]\n", encoding="utf-8")  # 커밋하지 않은 새 파일은 HEAD 에 없다
    with pytest.raises(RunnerRefused, match="HEAD"):
        runner._require_head_clean([new])


def test_crlf_in_the_working_tree_is_not_a_difference(repo):
    root, f = repo
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    runner._require_head_clean([f])


def test_without_git_or_outside_a_repository_the_check_fails_closed(repo, tmp_path, monkeypatch):
    _, f = repo
    plain = tmp_path / "plain"
    plain.mkdir()
    loose = plain / "cases.json"
    loose.write_text("[]", encoding="utf-8")
    with pytest.raises(RunnerRefused, match="git|HEAD"):
        runner._require_head_clean([loose])  # 저장소 밖

    def no_git(*a, **k):
        raise FileNotFoundError("git 없음")

    monkeypatch.setattr(runner.subprocess, "run", no_git)
    with pytest.raises(RunnerRefused, match="git"):
        runner._require_head_clean([f])


def test_a_modified_default_dev_file_makes_the_committed_check_refuse(repo, monkeypatch):
    """기준 파일을 고친 상태에서는 선택본과 기준이 같은 수정본이어도 거부된다(기준은 HEAD 커밋 객체)."""
    root, f = repo
    monkeypatch.setattr(runner, "_baseline_paths", lambda split: [f])
    f.write_text('[{"id": "x", "question": "바꾼 질문"}]\n', encoding="utf-8")
    with pytest.raises(RunnerRefused, match="HEAD"):
        runner.committed_rows("dev")


def test_the_real_baseline_files_of_this_checkout_are_clean_and_listed():
    paths = runner._baseline_paths("dev")
    names = {p.name for p in paths}
    assert {"cases_dev.json", "scenarios_dev.json", "splits.lock.json"} <= names
    assert [p.name for p in runner._baseline_paths("legacy")] == [adapter.LEGACY_CASES_PATH.name]
    runner._require_head_clean(paths)
    runner._require_head_clean(runner._baseline_paths("legacy"))
    runner.verify_committed(legacy("b-total"), "legacy")


def test_preflight_check_7_fails_when_the_cases_are_not_the_committed_ones(monkeypatch, tmp_path):
    from decimal import Decimal

    from evals.agent_eval.cost import Ledger, Scope

    def refuse(items, split):
        raise RunnerRefused("작업 트리가 HEAD 와 다르다")

    monkeypatch.setattr(runner, "verify_committed", refuse)
    results = tmp_path / "results"
    inp = preflight.PreflightInput(
        split="legacy", run_id="p", approve=Decimal("1"), model="claude-haiku-5-5", repeat=1,
        requested_ids=("b-total",), items=legacy("b-total"), missing_ids=(), calls_per_case=4,
        tokens_in=8000, tokens_out=500, results_root=results, default_results=results,
        ledger=Ledger((Scope.RUN, Scope.PROJECT), opening={Scope.PROJECT: Decimal(0)}),
    )  # fmt: skip
    check = preflight._check_cases(inp)
    assert check.status == preflight.FAIL and "HEAD" in check.detail
    assert isinstance(Path(__file__), Path)
