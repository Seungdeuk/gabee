"""누적 비용 집계 기준 시험(L0). 기준: docs/features/agent-eval.md '누적 비용 집계 기준'.

`store.opening_spent(root, …)` 는 **한 결과 폴더(root) 바로 아래 실행 폴더들의** `manifest.json` 의 `cost_usd` 합이다.
- 다른 작업 폴더(worktree)의 결과 폴더는 세지 않는다(2026-11-18 조사에서 실행기 누적이 수동 합계보다 $0.0312954 적었던 원인).
- `_rescore/` 같은 하위 폴더의 재채점 결과(모델 호출 0회, 비용 0)는 세지 않는다.
"""

import json
from decimal import Decimal as D
from pathlib import Path

from evals.agent_eval.store import opening_spent


def _manifest(root: Path, name: str, cost: str, calls: int = 1) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(
        json.dumps({"run_id": name, "stage": "other", "cost_usd": cost, "calls": calls}),
        encoding="utf-8",
    )


def test_sums_the_run_folders_directly_under_one_root(tmp_path):
    root = tmp_path / "results"
    _manifest(root, "real-dev-a", "0.0100000")
    _manifest(root, "real-dev-b", "0.0250000")
    assert opening_spent(root, "other")["project"] == D("0.0350000")


def test_rescore_results_are_not_counted(tmp_path):
    """재채점은 모델을 부르지 않는다. 하위 `_rescore/` 폴더는 합에 들어가지 않는다(값이 있어도 세지 않는다)."""
    root = tmp_path / "results"
    _manifest(root, "real-dev-a", "0.0100000")
    _manifest(root / "_rescore", "rescore-real-dev-a-x", "0.9000000")
    assert opening_spent(root, "other")["project"] == D("0.0100000")


def test_another_worktrees_results_root_is_not_seen(tmp_path):
    """결과 폴더가 둘로 나뉘면 각자의 합만 센다. 전체 누적은 두 폴더를 모두 합쳐 따로 확인해야 한다(문서의 수동 합계 절차)."""
    here, other = tmp_path / "a" / "results", tmp_path / "b" / "results"
    _manifest(here, "real-dev-a", "0.0100000")
    _manifest(other, "real-dev-old", "0.0312954")
    assert opening_spent(here, "other")["project"] == D("0.0100000")
    total = opening_spent(here, "other")["project"] + opening_spent(other, "other")["project"]
    assert total == D("0.0412954")


def test_a_run_folder_without_a_manifest_is_not_counted(tmp_path):
    """manifest 가 없는 폴더(예: `_fake`, `_rescore` 상위)는 비용 없이 건너뛴다."""
    root = tmp_path / "results"
    (root / "_fake" / "plan").mkdir(parents=True)
    _manifest(root, "real-dev-a", "0.0100000")
    assert opening_spent(root, "other")["project"] == D("0.0100000")
