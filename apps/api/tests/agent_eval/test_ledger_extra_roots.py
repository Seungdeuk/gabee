"""전역 비용 ledger 시험(L0): 여러 작업 폴더(worktree)의 결과 폴더를 합친 누적 비용.

기준: docs/features/agent-eval.md 'dev 36건 × 3회 반복 평가 실행 계획과 비용 통합 집계 개선안'. 환경변수
`GABEE_EVAL_EXTRA_RESULTS_ROOTS` 가 없으면 지금까지처럼 한 폴더의 합이다(`test_cost_accounting_rules.py`). 읽기 전용이고 파일을 바꾸지 않는다.
"""

import hashlib
import json
import os
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.agent_eval import cli, store
from evals.agent_eval.cost import CAPS, OTHER_RUN_SCOPES, BudgetExceeded, Ledger, Scope


def _manifest(
    root: Path,
    name: str,
    cost: str,
    stage: str = "other",
    started_at: str = "2026-11-13T07:00:00Z",
    loop_id: str | None = None,
    run_id: str | None = None,
) -> None:
    d = root / name
    d.mkdir(parents=True)
    body = {
        "run_id": run_id or name,
        "stage": stage,
        "cost_usd": cost,
        "calls": 1,
        "started_at": started_at,
    }
    if loop_id:
        body["loop_id"] = loop_id
    (d / "manifest.json").write_text(json.dumps(body), encoding="utf-8")


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode() + p.read_bytes())
    return h.hexdigest()


@pytest.fixture
def two_roots(tmp_path):
    here, other = tmp_path / "a" / "results", tmp_path / "b" / "results"
    _manifest(here, "real-dev-a", "0.1328580")
    _manifest(other, "real-dev-old", "0.0312954")
    return here, other


# ---------- 합산 ----------
def test_sums_the_current_root_and_every_extra_root(two_roots):
    here, other = two_roots
    reading = store.read_opening(here, "other", extra_roots=[other])
    assert reading.total == D("0.1641534")  # 실제 누적 실측 비용과 같은 모양: 0.1328580 + 0.0312954
    assert store.opening_spent(here, "other", extra_roots=[other])["project"] == D("0.1641534")
    assert [r.runs for r in reading.roots] == [1, 1] and reading.has_extra
    assert [r.cost for r in reading.roots] == [D("0.1328580"), D("0.0312954")]


def test_without_extra_roots_it_is_the_old_single_root_sum(two_roots):
    here, _ = two_roots
    reading = store.read_opening(here, "other")
    assert reading.total == D("0.1328580") and not reading.has_extra


def test_a_missing_primary_root_is_zero_but_extras_still_count(tmp_path):
    other = tmp_path / "b" / "results"
    _manifest(other, "real-dev-old", "0.0312954")
    reading = store.read_opening(tmp_path / "nope", "other", extra_roots=[other])
    assert reading.total == D("0.0312954")


def test_rescore_folders_and_manifestless_folders_are_skipped_in_every_root(two_roots):
    here, other = two_roots
    _manifest(other / "_rescore", "rescore-x", "0.9000000")
    (other / "_fake" / "plan").mkdir(parents=True)
    assert store.read_opening(here, "other", extra_roots=[other]).total == D("0.1641534")


def test_stage_sums_include_baseline_and_loop_runs_from_extra_roots(tmp_path):
    here, other = tmp_path / "a", tmp_path / "b"
    _manifest(here, "base-1", "0.0100000", stage="baseline")
    _manifest(other, "base-2", "0.0200000", stage="baseline")
    _manifest(other, "loop-1", "0.0400000", stage="loop", loop_id="L1")
    _manifest(other, "loop-2", "0.0800000", stage="loop", loop_id="L2")
    base = store.read_opening(here, "baseline", extra_roots=[other]).spent
    assert base["baseline"] == D("0.0300000") and base["project"] == D("0.1500000")
    loop = store.read_opening(here, "loop", loop_id="L1", extra_roots=[other]).spent
    assert loop["loop"] == D("0.0400000") and loop["project"] == D("0.1500000")


# ---------- 중복·충돌 ----------
def test_the_same_run_in_two_roots_is_counted_once(two_roots, tmp_path):
    here, other = two_roots
    _manifest(
        other, "real-dev-a", "0.1328580"
    )  # here 의 실행을 다른 폴더에 복사해 둔 경우(같은 run_id·started_at·비용)
    reading = store.read_opening(here, "other", extra_roots=[other])
    assert reading.total == D("0.1641534")
    assert reading.roots[1].skipped_duplicates == 1 and reading.roots[1].runs == 1


def test_the_same_root_listed_twice_or_as_the_primary_is_read_once(two_roots):
    here, other = two_roots
    detour = other / ".." / "results"  # 같은 폴더를 다른 모양의 경로로 적은 경우
    reading = store.read_opening(here, "other", extra_roots=[other, detour, here, here])
    assert reading.total == D("0.1641534") and len(reading.roots) == 2


def test_same_run_id_with_different_content_stops_instead_of_guessing(two_roots):
    here, other = two_roots
    _manifest(other, "real-dev-a", "0.5000000")  # 같은 run_id 인데 비용이 다르다
    with pytest.raises(ValueError, match="같은 실행 id 인데 내용이 다르다"):
        store.read_opening(here, "other", extra_roots=[other])
    other2 = other.parent / "results2"
    _manifest(other2, "real-dev-a", "0.1328580", started_at="2026-11-14T00:00:00Z")
    with pytest.raises(ValueError, match="내용이 다르다"):
        store.read_opening(here, "other", extra_roots=[other2])


# ---------- 합계를 조용히 줄이지 않는다 ----------
def test_a_configured_extra_root_that_does_not_exist_is_an_error(two_roots, tmp_path):
    here, _ = two_roots
    with pytest.raises(ValueError, match="추가 결과 폴더가 없다"):
        store.read_opening(here, "other", extra_roots=[tmp_path / "typo" / "results"])


def test_an_unreadable_manifest_in_an_extra_root_is_an_error(two_roots):
    here, other = two_roots
    (other / "broken").mkdir()
    (other / "broken" / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest 를 읽을 수 없다"):
        store.read_opening(here, "other", extra_roots=[other])
    (other / "broken" / "manifest.json").write_text('{"stage":"other"}', encoding="utf-8")
    with pytest.raises(ValueError, match="manifest 를 읽을 수 없다"):  # 비용이 없다
        store.read_opening(here, "other", extra_roots=[other])


# ---------- 환경변수 ----------
def test_env_parsing(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert store.extra_roots_from_env({}) == ()
    assert store.extra_roots_from_env({store.EXTRA_ROOTS_ENV: ""}) == ()
    assert store.extra_roots_from_env({store.EXTRA_ROOTS_ENV: f" {os.pathsep} "}) == ()
    value = f"{a}{os.pathsep}{os.pathsep}{b}{os.pathsep}"
    assert store.extra_roots_from_env({store.EXTRA_ROOTS_ENV: value}) == (a, b)
    with pytest.raises(ValueError, match="절대 경로"):
        store.extra_roots_from_env({store.EXTRA_ROOTS_ENV: "relative/results"})


# ---------- 읽기 전용 ----------
def test_reading_changes_no_file(two_roots):
    here, other = two_roots
    before = (_tree_hash(here), _tree_hash(other))
    store.read_opening(here, "other", extra_roots=[other])
    assert (_tree_hash(here), _tree_hash(other)) == before


# ---------- 실행 중 상한: 전체 프로젝트 상한과 개별 실행 상한을 모두 검사 ----------
def _ledger(spent: dict[str, D], approve: D | None = None) -> Ledger:
    caps = dict(CAPS)
    if approve is not None:
        caps[Scope.RUN] = min(caps[Scope.RUN], approve)
    opening = {s: spent[s.value] for s in OTHER_RUN_SCOPES if s is not Scope.RUN}
    return Ledger(OTHER_RUN_SCOPES, opening=opening, caps=caps)


def test_the_project_cap_uses_the_global_sum_not_just_this_folder(tmp_path):
    here, other = tmp_path / "a", tmp_path / "b"
    _manifest(here, "real-dev-a", "0.0100000")
    _manifest(other, "real-dev-big", "39.9990000")  # 다른 작업 폴더에 쌓인 지출
    alone = _ledger(store.opening_spent(here, "other"))
    alone.check_call("claude-haiku-5-5", 8000, 4096)  # 이 폴더만 보면 통과한다(옛 동작의 구멍)
    ledger = _ledger(store.opening_spent(here, "other", extra_roots=[other]))
    assert ledger.spent[Scope.PROJECT] == D("40.0090000")
    with pytest.raises(BudgetExceeded) as info:
        ledger.check_call("claude-haiku-5-5", 8000, 4096)
    assert info.value.scope is Scope.PROJECT


def test_the_per_run_cap_still_applies_with_a_global_opening(two_roots):
    here, other = two_roots
    spent = store.opening_spent(here, "other", extra_roots=[other])
    ledger = _ledger(
        spent, approve=D("0.0010000")
    )  # 프로젝트 합은 충분히 남았지만 이번 실행 승인 금액이 작다
    with pytest.raises(BudgetExceeded) as info:
        ledger.check_call("claude-haiku-5-5", 8000, 4096)
    assert info.value.scope is Scope.RUN


def test_cli_estimate_ledger_reads_the_env_roots(two_roots, monkeypatch):
    here, other = two_roots
    args, plan = SimpleNamespace(stage="other"), SimpleNamespace(approve=None)
    monkeypatch.delenv(store.EXTRA_ROOTS_ENV, raising=False)
    assert cli._estimate_ledger(args, plan, here).spent[Scope.PROJECT] == D("0.1328580")
    monkeypatch.setenv(store.EXTRA_ROOTS_ENV, str(other))
    assert cli._estimate_ledger(args, plan, here).spent[Scope.PROJECT] == D("0.1641534")


def test_the_breakdown_lines_name_each_root_and_the_global_total(two_roots):
    here, other = two_roots
    text = "\n".join(store.read_opening(here, "other", extra_roots=[other]).lines())
    assert str(here.resolve()) in text and str(other.resolve()) in text
    assert "0.1641534" in text and "프로젝트 누적(전역)" in text
