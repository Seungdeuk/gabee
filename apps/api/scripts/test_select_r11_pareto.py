"""R11 파레토 열세 제거(§7-4 1단계)와 0.1%p 반올림 비교 시험: 우수한 후보가 거꾸로 제거되지 않는지, 입력 순서에 결과가 흔들리지 않는지 확인한다."""

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import select_r11 as s  # noqa: E402


def c(label, rec, f1, exp, **kw):
    return {"label": label, "seed": kw.get("seed", 7), "recall": rec, "f1": f1, "exposure": exp, "targets_macro": kw.get("tm", 0.15), "neg_fpr_macro": 0.03, "precision": 0.8, "group_sd_sum": 0.03, "latency": None}


def survivors(cands):
    chosen, info = s.select_candidate(cands)
    removed = set(info["dominated_removed"])
    return {x["label"] for x in cands} - removed, chosen, info


def dominates_user_def(a, b):
    """사용자가 정의한 규칙을 반올림값에서 그대로 쓴 독립 구현: A Recall>=B, A F1>=B, A 노출<=B, 하나 이상 엄격히 우수."""
    ra, rb = (s.rnd(a["recall"], 1), s.rnd(a["f1"], 1), s.rnd(a["exposure"], 1)), (s.rnd(b["recall"], 1), s.rnd(b["f1"], 1), s.rnd(b["exposure"], 1))
    return ra[0] >= rb[0] and ra[1] >= rb[1] and ra[2] <= rb[2] and (ra[0] > rb[0] or ra[1] > rb[1] or ra[2] < rb[2])


def test_superior_candidate_removes_inferior_and_never_the_reverse():
    a = c("A", 0.76, 0.80, 0.15)
    b = c("B", 0.74, 0.78, 0.17)
    for order in itertools.permutations([a, b]):
        sv, chosen, _ = survivors(list(order))
        assert sv == {"A"} and chosen == "A"


def test_each_single_metric_improvement_alone_is_enough_when_others_equal():
    base = c("B", 0.75, 0.80, 0.16)
    for a in (c("A", 0.76, 0.80, 0.16), c("A", 0.75, 0.81, 0.16), c("A", 0.75, 0.80, 0.15)):
        assert survivors([a, base])[0] == {"A"}


def test_tradeoff_candidates_are_both_kept():
    a = c("A", 0.80, 0.78, 0.16)  # Recall 우세
    b = c("B", 0.76, 0.82, 0.16)  # F1 우세
    assert survivors([a, b])[0] == {"A", "B"}


def test_identical_metrics_do_not_eliminate_each_other():
    a, b = c("A", 0.75, 0.80, 0.16, seed=1), c("B", 0.75, 0.80, 0.16, seed=2)
    assert survivors([a, b])[0] == {"A", "B"}


def test_rounding_half_up_and_tiny_differences_are_equal():
    assert s.rnd(0.7605, 1) == 76.1 and s.rnd(0.76049, 1) == 76.0 and s.rnd(0.7625, 2) == 76.25
    a = c("A", 0.7604, 0.80, 0.16)  # 76.0
    b = c("B", 0.7596, 0.80, 0.16)  # 76.0 -> 같은 값이므로 지배하지 않는다
    assert survivors([a, b])[0] == {"A", "B"}
    a2 = c("A", 0.7606, 0.80, 0.16)  # 76.1 vs 75.9 -> 지배
    b2 = c("B", 0.7594, 0.80, 0.16)
    assert survivors([a2, b2])[0] == {"A"}


def test_property_survivors_are_exactly_the_non_dominated_and_nonempty_and_order_independent():
    rng = random.Random(1)
    for _ in range(400):
        n = rng.randint(2, 9)
        cs = [c(f"M{i}", round(rng.uniform(0.70, 0.80), 3), round(rng.uniform(0.74, 0.84), 3), round(rng.uniform(0.12, 0.22), 3), seed=i) for i in range(n)]
        sv, chosen, _ = survivors(cs)
        expected = {x["label"] for x in cs if not any(dominates_user_def(o, x) for o in cs if o is not x)}
        assert sv == expected and sv and chosen in sv
        sh = cs[:]
        rng.shuffle(sh)
        assert survivors(sh)[0] == sv
        # 반올림값 기준으로 한 지표가 유일한 최고이면 그 모델은 절대 제거되지 않는다
        for key, rev in (("recall", True), ("f1", True), ("exposure", False)):
            vals = [s.rnd(x[key], 1) for x in cs]
            best = max(vals) if rev else min(vals)
            if vals.count(best) == 1:
                assert cs[vals.index(best)]["label"] in sv
