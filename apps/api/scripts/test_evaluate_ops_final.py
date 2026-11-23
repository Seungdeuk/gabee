"""운영 교체 평가 실행기 시험(모델·평가셋 없이 합성 집계로). 판정 논리, 쌍체 부트스트랩, 재실행 방지, 기준·모델 해시 고정."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_ops_final as e  # noqa: E402

CRIT = json.loads((e.OPS / "ops_decision_criteria.json").read_text(encoding="utf-8"))
TYPES = ["A1", "B1", "C2", "D1", "D1P", "LONGNAME", "NEWNAME", "ORGLOC_MIX", "NEG_X", "NEG_Y"]
ROW = {"A1": (100, 70, 0, 10, 20, 70, 10, 0, 0, 0)}  # n_gold, ex, bo, pa, fu, tp, fpg, fpn, neg_n, neg_flag


def table(exposure, recall_ex, neg_flag=2, d1_flag=20, extra_fp=10):
    """유형별 합계 배열. exposure: 노출 수(100 중), recall_ex: exact 수."""
    arr = np.zeros((len(TYPES), len(e.COLS)), dtype=np.int64)
    for i, t in enumerate(TYPES):
        if t.startswith("NEG"):
            arr[i] = [0, 0, 0, 0, 0, 0, 0, neg_flag, 100, neg_flag]
        elif t == "D1":
            arr[i] = [0, 0, 0, 0, 0, 0, 0, d1_flag, 100, d1_flag]
        else:
            arr[i] = [100, recall_ex, 100 - exposure - recall_ex, exposure // 2, exposure - exposure // 2, recall_ex, extra_fp, 0, 0, 0]
    return arr


def point_ci(mA, mB, half=0.5):
    ci = {k: [mB[k] - mA[k] - half / 100, mB[k] - mA[k] + half / 100] for k in mA if not k.endswith("n_gold") and k != "n_gold"}
    return ci


def run_decide(a_arr, b_arr, pa=(100, 12), pb=(100, 40), half=0.5):
    mA, mB = e.metrics_from(a_arr, np.array(pa), TYPES), e.metrics_from(b_arr, np.array(pb), TYPES)
    ci = point_ci(mA, mB, half)
    return e.decide(CRIT, mA, mB, ci, TYPES)


def test_clear_improvement_passes_all_primary_checks():
    verdict, checks, _ = run_decide(table(exposure=30, recall_ex=50, extra_fp=40), table(exposure=8, recall_ex=84, extra_fp=10))
    assert verdict == "PRIMARY_ALL_PASS" and all(checks.values()), checks


def test_target_type_worsening_beyond_limit_blocks_replacement():
    a, b = table(30, 50, extra_fp=40), table(8, 84, extra_fp=10)
    i = TYPES.index("B1")
    b[i][3], b[i][4] = 20, 20  # B1 노출 40 으로 악화(S0 30)
    verdict, checks, _ = run_decide(a, b)
    assert verdict == "KEEP_S0" and not checks["P6_target_types_exposure"]


def test_negative_fpr_increase_blocks_even_with_big_recall_gain():
    verdict, checks, _ = run_decide(table(30, 50, neg_flag=2, extra_fp=40), table(8, 84, neg_flag=10, extra_fp=10))
    assert verdict == "KEEP_S0" and not checks["P5_negative_fpr"]


def test_ci_crossing_threshold_means_keep_s0():
    a, b = table(30, 50, extra_fp=40), table(18, 62, extra_fp=10)  # 점추정 +12pp 이지만 구간 하한이 5 미만이 되도록 넓은 구간
    verdict, checks, _ = run_decide(a, b, half=8.0)
    assert verdict == "KEEP_S0" and not checks["P1_recall"]


def test_paired_bootstrap_is_deterministic_and_pairs_models():
    rng = np.random.default_rng(1)
    n = 60
    A = rng.integers(0, 3, (n, 2, len(e.COLS)))
    B = A.copy()
    B[:, :, 1] += 1  # 모든 군집에서 B 가 exact 하나 더
    pa = np.zeros((n, 2), dtype=np.int64)
    ci1 = e.bootstrap({"A": (A, pa), "B": (B, pa)}, ["T1", "T2"], 200, 7)
    ci2 = e.bootstrap({"A": (A, pa), "B": (B, pa)}, ["T1", "T2"], 200, 7)
    assert str(ci1) == str(ci2)  # NaN 포함 비교
    assert ci1["exact_recall"][0] > 0  # 같은 재표본을 쓰므로 일관된 개선은 0 을 포함하지 않는다


def test_criteria_hash_must_match_lock(tmp_path):
    crit = tmp_path / "c.json"
    crit.write_text(json.dumps(CRIT), encoding="utf-8")
    crit.write_text(crit.read_text(encoding="utf-8") + " ", encoding="utf-8")  # 기준 파일이 바뀐 상황
    with pytest.raises(SystemExit):
        e.main(["--rehearsal-data", str(tmp_path / "x.jsonl"), "--criteria", str(crit), "--out", str(tmp_path / "o.json")])


def test_sealed_mode_refuses_second_run(tmp_path, monkeypatch):
    root = tmp_path / "ops"
    sealed = root / "sealed"
    sealed.mkdir(parents=True)
    f = sealed / "r11_stress_independent.jsonl"
    f.write_text("", encoding="utf-8")
    (sealed / "MANIFEST.sha256").write_text(f"{e.sha(f)} *{f.name}\n", encoding="utf-8")
    (root / "EVALUATED.lock").write_text("{}", encoding="utf-8")  # 이미 한 번 평가한 상황
    monkeypatch.setattr(e, "verify_models", lambda lock: None)
    with pytest.raises(SystemExit) as ex:
        e.main(["--sealed-dir", str(sealed), "--out", str(tmp_path / "o.json")])
    assert "EVALUATED.lock" in str(ex.value)


def test_seal_tampering_is_detected(tmp_path):
    d = tmp_path / "sealed"
    d.mkdir()
    (d / "a.jsonl").write_text("x", encoding="utf-8")
    (d / "MANIFEST.sha256").write_text(f"{e.sha(d / 'a.jsonl')} *a.jsonl\n", encoding="utf-8")
    e.verify_seal(d)
    (d / "a.jsonl").write_text("y", encoding="utf-8")
    with pytest.raises(SystemExit):
        e.verify_seal(d)
