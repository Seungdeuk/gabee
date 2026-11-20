"""0.1%p 반올림 비교가 R11 후보 선정에 미치는 영향 모의 분석(합성 후보, B 학습 결과와 무관). 반올림 없음/0.1%p/0.5%p 와 선정 결과가 달라지는 비율을 센다."""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import select_r11 as s  # noqa: E402


def make(rng, n):
    out = []
    for i in range(n):
        q = rng.gauss(0, 1)
        out.append({"label": f"M{i}", "seed": i, "recall": 0.75 + 0.025 * q + rng.gauss(0, 0.01), "f1": 0.80 + 0.02 * q + rng.gauss(0, 0.01),
                    "exposure": 0.16 - 0.02 * q + rng.gauss(0, 0.008), "targets_macro": rng.uniform(0.10, 0.20), "neg_fpr_macro": rng.uniform(0.01, 0.05),
                    "precision": rng.uniform(0.75, 0.88), "group_sd_sum": rng.uniform(0.01, 0.06), "latency": None})
    return out


def run(step_nd):
    orig = s.rnd
    if step_nd == "none":
        s.rnd = lambda x, nd: round(100 * x, 9)
    elif step_nd == "0.5":
        s.rnd = lambda x, nd: round(round(100 * x * 2) / 2, 9)
    try:
        rng = random.Random(7)
        res = []
        for _ in range(5000):
            cs = make(rng, rng.randint(3, 10))
            chosen, info = s.select_candidate(cs)
            res.append((chosen, set(info["dominated_removed"]), info.get("rank_sum", {}), len(info.get("tiebreak_steps_used", []))))
        return res
    finally:
        s.rnd = orig


base = run("0.1")
out = {"trials": len(base)}
for name in ("none", "0.5"):
    other = run(name)
    out[f"vs_{name}"] = {"selected_differs_pct": round(100 * sum(a[0] != b[0] for a, b in zip(base, other, strict=True)) / len(base), 2),
                         "dominated_set_differs_pct": round(100 * sum(a[1] != b[1] for a, b in zip(base, other, strict=True)) / len(base), 2)}
out["rank_sum_ties_needing_tiebreak_pct(0.1)"] = round(100 * sum(1 for a in base if a[3] > 0) / len(base), 2)
print(json.dumps(out, indent=1))
