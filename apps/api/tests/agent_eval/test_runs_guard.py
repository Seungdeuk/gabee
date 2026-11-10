"""테스트 분할 평가 횟수 문지기 시험(L0). 파일만 쓰고 LLM·DB 는 쓰지 않는다."""

import json
import multiprocessing
import threading
from datetime import date
from pathlib import Path

import pytest

from evals.agent_eval import runs_guard as rg
from evals.agent_eval.schema import Case

DAY = date(2026, 11, 10)
H1, H2 = "a" * 40, "b" * 40
Err = rg.TestRunsError


def _runs(tmp_path) -> Path:
    path = tmp_path / "test_runs.json"
    rg.init_runs_file(path)
    return path


def _case(cid):
    return Case.model_validate(
        {
            "id": cid,
            "split": "test",
            "category": "C",
            "scenario": "single_tool",
            "agent_path": "schedule",
            "question": "질문",
            "meta": {"synthetic": True},
        }
    )


def _split(tmp_path, ids=("t1", "t2")) -> Path:
    path = tmp_path / "test_split.json"
    path.write_text(json.dumps([_case(i).model_dump(mode="json") for i in ids]), encoding="utf-8")
    return path


def test_missing_or_damaged_history_stops_everything_and_is_never_recreated(tmp_path):
    path = tmp_path / "test_runs.json"
    split = tmp_path / "never_opened.json"  # 이력 확인이 먼저라 이 파일은 열리지도 않는다
    with pytest.raises(Err):
        rg.load_test_cases(path, split, "r1", "baseline", DAY)
    assert not path.exists()
    for bad in (
        "{",
        "[]",
        '{"version": 2, "runs": []}',
        '{"version": 1, "runs": [], "extra": 1}',
        '{"version": 1, "runs": [{"run_id": "r"}]}',
        json.dumps(
            {
                "version": 1,
                "runs": [
                    {
                        "run_id": "r",
                        "purpose": "baseline",
                        "split_hash": H1,
                        "date": "2026-11-10",
                        "cases": {"t1": "weird"},
                    }
                ],
            }
        ),
    ):
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(Err):
            rg.load_test_cases(path, split, "r1", "baseline", DAY)
        assert path.read_text(encoding="utf-8") == bad  # 고쳐 쓰거나 비우지 않는다


def test_init_does_not_overwrite_an_existing_history(tmp_path):
    path = _runs(tmp_path)
    with pytest.raises(Err):
        rg.init_runs_file(path)


def test_each_case_gets_one_baseline_and_one_final_only(tmp_path):
    path = _runs(tmp_path)
    rg.reserve(path, "b1", "baseline", H1, ["t1", "t2"], DAY)
    rg.reserve(path, "f1", "final", H1, ["t1"], DAY)
    with pytest.raises(Err, match="t1"):
        rg.reserve(path, "b2", "baseline", H1, ["t1"], DAY)
    with pytest.raises(Err, match="t1"):
        rg.reserve(path, "f2", "final", H1, ["t1"], DAY)
    rg.reserve(path, "f3", "final", H1, ["t2"], DAY)  # t2 의 final 은 아직 없다


def test_a_partly_over_limit_reservation_reserves_nothing(tmp_path):
    path = _runs(tmp_path)
    rg.reserve(path, "b1", "baseline", H1, ["t1"], DAY)
    before = path.read_text(encoding="utf-8")
    with pytest.raises(Err):
        rg.reserve(path, "b2", "baseline", H1, ["t1", "t9"], DAY)
    assert path.read_text(encoding="utf-8") == before
    with pytest.raises(Err):
        rg.reserve(path, "b1", "final", H1, ["t9"], DAY)  # 같은 run_id 로 다시 예약하지 못한다


def test_a_case_cannot_be_started_twice_even_after_a_crash(tmp_path):
    path = _runs(tmp_path)
    rg.reserve(path, "b1", "baseline", H1, ["t1", "t2"], DAY)
    with pytest.raises(Err):
        rg.finish_case(path, "b1", "t1")  # 시작하지 않은 사례는 끝낼 수 없다
    rg.start_case(path, "b1", "t1")
    with pytest.raises(Err):
        rg.start_case(path, "b1", "t1")  # 끊기고 다시 와도(started) 다시 시작하지 못한다
    rg.finish_case(path, "b1", "t1")
    with pytest.raises(Err):
        rg.start_case(path, "b1", "t1")
    assert rg.status(path, "b1") == {"t1": "done", "t2": "pending"}


def test_load_reserves_before_returning_and_refuses_when_exhausted(tmp_path):
    path, split = _runs(tmp_path), _split(tmp_path)
    cases, digest = rg.load_test_cases(path, split, "b1", "baseline", DAY)
    assert [c.id for c in cases] == ["t1", "t2"] and len(digest) == 64
    assert rg.status(path, "b1") == {"t1": "pending", "t2": "pending"}  # 돌려주기 전에 예약돼 있다
    with pytest.raises(Err):
        rg.load_test_cases(path, split, "b2", "baseline", DAY)  # 새 실행 id 로 다시 평가하지 못한다


def test_resume_runs_only_pending_cases_and_reports_interrupted_ones(tmp_path):
    path, split = _runs(tmp_path), _split(tmp_path, ("t1", "t2", "t3"))
    rg.load_test_cases(path, split, "b1", "baseline", DAY)
    rg.start_case(path, "b1", "t1")
    rg.finish_case(path, "b1", "t1")
    rg.start_case(path, "b1", "t2")  # 여기서 끊김
    cases, _ = rg.load_test_cases(path, split, "b1", "baseline", DAY)  # 같은 실행 id 로 이어서
    assert [c.id for c in cases] == ["t3"]
    assert rg.status(path, "b1")["t2"] == "started"  # 호출한 쪽이 끊긴 사례로 알 수 있다
    with pytest.raises(Err):
        rg.load_test_cases(path, split, "b1", "final", DAY)  # 목적을 바꿔 이어 돌릴 수 없다
    split.write_text(split.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(Err):
        rg.load_test_cases(path, split, "b1", "baseline", DAY)  # 분할 파일이 바뀌었다


def test_a_split_with_non_test_cases_is_refused(tmp_path):
    path = _runs(tmp_path)
    split = tmp_path / "mixed.json"
    mixed = _case("x").model_dump(mode="json") | {"split": "dev"}
    split.write_text(json.dumps([mixed]), encoding="utf-8")
    with pytest.raises(Err):
        rg.load_test_cases(path, split, "b1", "baseline", DAY)
    assert json.loads(path.read_text("utf-8"))["runs"] == []  # 예약도 남지 않았다


def test_threads_racing_for_the_same_cases_only_one_wins(tmp_path):
    path = _runs(tmp_path)
    results = []

    def go(i):
        try:
            rg.reserve(path, f"f{i}", "final", H1, ["t1", "t2"], DAY)
            results.append("ok")
        except Err:
            results.append("refused")

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ok"] + ["refused"] * 7
    assert len(json.loads(path.read_text("utf-8"))["runs"]) == 1


def _process_go(args):
    path, i = args
    try:
        rg.reserve(Path(path), f"f{i}", "final", H2, ["t1"], DAY)
        return "ok"
    except Err:
        return "refused"


def test_separate_processes_racing_for_the_same_case_only_one_wins(tmp_path):
    path = _runs(tmp_path)
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        results = pool.map(_process_go, [(str(path), i) for i in range(6)])
    assert sorted(results) == ["ok"] + ["refused"] * 5
    assert json.loads(path.read_text("utf-8"))["runs"][0]["cases"] == {"t1": "pending"}
