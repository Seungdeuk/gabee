"""검색 지표 단위 시험(순수 함수). 분모와 예외 규칙이 문서 정의와 같은지 본다."""

import pytest

from evals.search_quality import metrics


def test_hit_recall_mrr_use_gold_only_and_rank_of_first_gold():
    m = metrics.case_metrics(["x", "ctx", "g1", "y", "g2"], ["g1", "g2", "g3"], ["ctx"])
    assert m["hit"] == 1.0
    assert m["recall"] == pytest.approx(2 / 3)
    assert m["mrr"] == pytest.approx(1 / 3)  # 맥락 글(ctx)은 순위에 쓰지 않는다
    assert (m["gold_hits"], m["context_hits"], m["irrelevant"]) == (2, 1, 2)


def test_precision_at_k_has_fixed_denominator_and_returned_precision_is_separate():
    m = metrics.case_metrics(["g1", "ctx"], ["g1"], ["ctx"])
    assert m["precision_at_k"] == pytest.approx(1 / 10)  # 반환이 2건이어도 10 으로 나눈다
    assert m["precision_returned"] == pytest.approx(1 / 2)  # 맥락 글은 정답으로 세지 않는다
    empty = metrics.case_metrics([], ["g1"], [])
    assert empty["precision_at_k"] == 0.0 and empty["precision_returned"] is None
    assert empty["hit"] == 0.0 and empty["recall"] == 0.0 and empty["mrr"] == 0.0


def test_only_the_top_k_are_scored():
    ranked = [f"n{i}" for i in range(10)] + ["g1"]
    assert metrics.case_metrics(ranked, ["g1"], [])["hit"] == 0.0  # 11번째는 Hit@10 에서 빠진다
    assert metrics.case_metrics(ranked, ["g1"], [], k=20)["hit"] == 1.0


def test_no_gold_case_has_no_quality_numbers():
    m = metrics.case_metrics(["a"], [], [])
    assert "hit" not in m and "recall" not in m and m["returned"] == 1


def test_aggregate_excludes_undefined_returned_precision_but_counts_it():
    rows = [
        metrics.case_metrics(["g"], ["g"], []),
        metrics.case_metrics([], ["g"], []),
    ]
    agg = metrics.aggregate(rows)
    assert agg["cases"] == 2 and agg["hit"] == 0.5 and agg["mrr"] == 0.5
    assert agg["precision_at_k"] == pytest.approx(0.05)
    assert agg["precision_returned"] == 1.0 and agg["precision_returned_undefined"] == 1


def test_no_answer_counts_empty_nonempty_and_violations():
    out = metrics.no_answer([{"returned": 0, "violations": 0}, {"returned": 2, "violations": 1}])
    assert out == {"cases": 2, "correct_empty": 1, "nonempty": 1, "violations": 1}
