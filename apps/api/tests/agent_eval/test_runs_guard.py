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
H1, H2, CAND, CAND2 = "a" * 40, "b" * 40, "c" * 40, "d" * 40
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


def _split(tmp_path, ids=("t1", "t2"), name="test_split.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps([_case(i).model_dump(mode="json") for i in ids]), encoding="utf-8")
    return path


def _reserve(path, run_id="b1", purpose="baseline", ids=("t1", "t2"), cand=CAND):
    rg.reserve(path, run_id, purpose, H1, cand, list(ids), DAY)


def _load(path, split, run_id="b1", purpose="baseline", cand=CAND):
    return rg.load_test_cases(path, split, run_id, purpose, cand, DAY)


def test_missing_or_damaged_history_stops_everything_and_is_never_recreated(tmp_path):
    path = tmp_path / "test_runs.json"
    split = tmp_path / "never_opened.json"  # 이력 확인이 먼저라 이 파일은 열리지도 않는다
    with pytest.raises(Err):
        _load(path, split)
    assert not path.exists()
    run = {
        "run_id": "r",
        "purpose": "baseline",
        "split_hash": H1,
        "candidate": CAND,
        "date": "2026-11-10",
        "cases": {"t1": "weird"},
    }
    for bad in (
        "{",
        "[]",
        '{"version": 2, "runs": []}',
        '{"version": 1, "runs": [], "extra": 1}',
        '{"version": 1, "runs": [{"run_id": "r"}]}',
        json.dumps({"version": 1, "runs": [run]}),
        json.dumps({"version": 1, "runs": [{**run, "cases": {"t1": "done"}, "candidate": "x"}]}),
    ):
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(Err):
            _load(path, split)
        assert path.read_text(encoding="utf-8") == bad  # 고쳐 쓰거나 비우지 않는다


def test_init_does_not_overwrite_an_existing_history(tmp_path):
    path = _runs(tmp_path)
    with pytest.raises(Err):
        rg.init_runs_file(path)


def test_each_purpose_has_exactly_one_run_so_cases_cannot_be_split_across_candidates(tmp_path):
    path = _runs(tmp_path)
    _reserve(path, "b1", "baseline", ("t1", "t2"))
    _reserve(path, "f1", "final", ("t1", "t2", "t3"))  # 한 목적에 한 번, 분할 전체
    with pytest.raises(Err, match="한 번뿐"):
        _reserve(path, "b2", "baseline", ("t3",))  # 겹치지 않는 사례 묶음도 거부
    with pytest.raises(Err, match="한 번뿐"):
        _reserve(path, "f2", "final", ("renamed1", "renamed2"))  # 사례 id 를 바꿔도 거부
    with pytest.raises(Err, match="이미 있는 실행 id"):
        _reserve(path, "b1", "final", ("t9",))


def test_names_are_validated_before_writing_so_the_file_never_becomes_unreadable(tmp_path):
    path = _runs(tmp_path)
    before = path.read_text(encoding="utf-8")
    bad_ids = (
        dict(run_id="베이스라인 1"),
        dict(run_id="a/b"),
        dict(ids=("한글",)),
        dict(ids=("x" * 70,)),
        dict(ids=("t1", "t1")),
        dict(ids=()),
        dict(cand="not-hex!"),
        dict(purpose="other"),
    )
    for kwargs in bad_ids:
        with pytest.raises(Err):
            _reserve(path, **kwargs)
    assert path.read_text(encoding="utf-8") == before
    _reserve(path)  # 그 뒤에도 정상 예약이 된다


def test_a_case_cannot_be_started_twice_even_after_a_crash(tmp_path):
    path = _runs(tmp_path)
    _reserve(path)
    with pytest.raises(Err):
        rg.finish_case(path, "b1", "t1")  # 시작하지 않은 사례는 끝낼 수 없다
    rg.start_case(path, "b1", "t1")
    with pytest.raises(Err):
        rg.start_case(path, "b1", "t1")  # 끊기고 다시 와도(started) 다시 시작하지 못한다
    rg.finish_case(path, "b1", "t1")
    with pytest.raises(Err):
        rg.start_case(path, "b1", "t1")
    assert rg.status(path, "b1") == {"t1": "done", "t2": "pending"}


def test_cases_are_returned_only_after_reservation_and_iterated_once_with_start_marks(tmp_path):
    path, split = _runs(tmp_path), _split(tmp_path)
    guarded, digest = _load(path, split)
    assert guarded.ids() == ["t1", "t2"] and len(digest) == 64 and len(guarded) == 2
    assert rg.status(path, "b1") == {"t1": "pending", "t2": "pending"}  # 돌려주기 전에 예약돼 있다
    seen = []
    for case in guarded:
        seen.append((case.id, dict(rg.status(path, "b1"))[case.id]))  # 내줄 때는 이미 started
    assert seen == [("t1", "started"), ("t2", "started")]
    assert set(rg.status(path, "b1").values()) == {"done"}
    with pytest.raises(Err):
        list(guarded)  # 한 번만 반복할 수 있다(열람을 되풀이하지 못한다)
    with pytest.raises(Err):
        _load(path, split, "b2")  # 새 실행 id 로 다시 평가하지 못한다


def test_breaking_out_of_the_loop_leaves_the_case_started_and_never_viewable_again(tmp_path):
    path, split = _runs(tmp_path), _split(tmp_path, ("t1", "t2", "t3"))
    guarded, _ = _load(path, split)
    for case in guarded:
        if case.id == "t2":
            break  # 결과를 본 뒤 끊는다
    assert rg.status(path, "b1") == {"t1": "done", "t2": "started", "t3": "pending"}
    resumed, _ = _load(path, split)  # 같은 실행 id 로 이어서
    assert resumed.ids() == ["t3"] and resumed.interrupted == ["t2"]
    assert [c.id for c in resumed] == ["t3"]


def test_resume_requires_the_same_purpose_split_file_and_candidate(tmp_path):
    path, split = _runs(tmp_path), _split(tmp_path)
    _load(path, split)
    with pytest.raises(Err):
        _load(path, split, purpose="final")
    with pytest.raises(Err):
        _load(path, split, cand=CAND2)  # 다른 후보로 이어 돌릴 수 없다
    split.write_text(split.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(Err):
        _load(path, split)  # 분할 파일이 바뀌었다


def test_a_split_with_non_test_cases_is_refused(tmp_path):
    path = _runs(tmp_path)
    split = tmp_path / "mixed.json"
    mixed = _case("x").model_dump(mode="json") | {"split": "dev"}
    split.write_text(json.dumps([mixed]), encoding="utf-8")
    with pytest.raises(Err):
        _load(path, split)
    assert json.loads(path.read_text("utf-8"))["runs"] == []  # 예약도 남지 않았다


def test_a_locked_or_unwritable_history_fails_closed_with_a_clear_error(tmp_path, monkeypatch):
    path = _runs(tmp_path)
    before = path.read_text(encoding="utf-8")

    def deny(src, dst):
        raise PermissionError("편집기가 열고 있다")

    monkeypatch.setattr(rg.os, "replace", deny)
    with pytest.raises(Err, match="쓰지 못했다"):
        _reserve(path)
    monkeypatch.undo()
    assert path.read_text(encoding="utf-8") == before
    assert not list(tmp_path.glob(".test_runs-*.tmp"))  # 임시 파일이 남지 않는다


def test_threads_racing_for_the_same_purpose_only_one_wins(tmp_path):
    path = _runs(tmp_path)
    results = []

    def go(i):
        try:
            rg.reserve(path, f"f{i}", "final", H1, CAND, ["t1", "t2"], DAY)
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
        rg.reserve(Path(path), f"f{i}", "final", H2, CAND, ["t1"], DAY)
        return "ok"
    except Err:
        return "refused"


def test_separate_processes_racing_for_the_same_purpose_only_one_wins(tmp_path):
    path = _runs(tmp_path)
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        results = pool.map(_process_go, [(str(path), i) for i in range(6)])
    assert sorted(results) == ["ok"] + ["refused"] * 5
    assert json.loads(path.read_text("utf-8"))["runs"][0]["cases"] == {"t1": "pending"}


def test_concurrent_start_of_the_same_case_lets_only_one_run_it(tmp_path):
    path = _runs(tmp_path)
    _reserve(path, ids=("t1",))
    results = []

    def go():
        try:
            rg.start_case(path, "b1", "t1")
            results.append("ok")
        except Err:
            results.append("refused")

    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["ok"] + ["refused"] * 7
