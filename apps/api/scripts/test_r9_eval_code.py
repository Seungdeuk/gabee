"""R9 평가 코드(지표 산출·게이트 판정) 검증: 모델 없이 예측 함수를 주입해 기대 수치와 정확히 일치하는지 확인한다. 봉인 평가셋은 쓰지 않는다.

실행: python scripts/test_r9_eval_code.py
"""

import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import evaluate_r8_dev as D  # noqa: E402
import r8_eval_lib as L  # noqa: E402

EV = D.EV


def rows(p):
    return D.load(p)


def test_metrics_on_real_dev_rows():
    r = [x for x in rows(D.MAIN5["v14_realistic"]) if not any(e - s == 1 for s, e in L.gold_person(x))]
    gold = lambda row: L.gold_person(row)
    oracle = L.score_rows(r, pred_fn=lambda row: gold(row))
    assert oracle["total_exposure_rate"] == 0 and oracle["prf"]["f1"] == 1.0 and oracle["neg_flagged"] == 0 and oracle["fp_boundary"] == 0 and oracle["fp_pure"] == 0
    none = L.score_rows(r, pred_fn=lambda row: [])
    assert none["total_exposure_rate"] == 1.0 and none["full"] == none["n_gold_spans"] and none["prf"]["tp"] == 0 and none["prf"]["fn"] == none["n_gold_spans"]
    cut = L.score_rows(r, pred_fn=lambda row: [(a, b - 1) for a, b in gold(row)])
    assert cut["partial"] == cut["n_gold_spans"] and cut["full"] == 0 and cut["prf"]["tp"] == 0 and cut["prf"]["fp"] == cut["n_gold_spans"] and cut["fp_boundary"] == cut["n_gold_spans"]
    over = L.score_rows(r, pred_fn=lambda row: [(a, b + 1) for a, b in gold(row)])
    assert over["total_exposure_rate"] == 0 and over["prf"]["f1"] == 0 and over["fp_boundary"] == over["n_gold_spans"]      # 과확장은 노출 0이지만 Exact 는 틀림
    negs = [x for x in r if not L.gold_person(x)]
    flag = L.score_rows(r, pred_fn=lambda row: [(0, 2)] if not L.gold_person(row) else gold(row))
    assert flag["neg_flagged"] == len(negs) and flag["nonperson_fpr"] == 1.0 and flag["total_exposure_rate"] == 0
    # 다중 구간 문장: 둘째 이름 미탐은 노출 1건, 첫 구간만 맞춘 이전 채점 방식과 구분된다
    multi = [x for x in rows(D.MAIN5["realistic_family"]) if len(L.gold_person(x)) >= 2][:5]
    first_only = lambda row: [L.gold_person(row)[0]]
    s = L.score_rows(multi, pred_fn=first_only)
    assert s["full"] == sum(len(L.gold_person(x)) - 1 for x in multi) and s["prf"]["fn"] == s["full"]
    leg = L.score_rows(multi, legacy_first_only=True, pred_fn=first_only)
    assert leg["n_gold_spans"] == len(multi) and leg["total_exposure_rate"] == 0       # 이전 방식은 둘째 이후 구간을 못 본다


def test_wilson_and_macro():
    ci = L.wilson(0, 661)
    assert abs(ci[1] - 0.0058) < 0.0003 and ci[0] == 0.0
    assert L.macro([0.1, 0.3, None]) == 0.2


def _res(exposure, f1, fp, om, sets_exp=None, sets_fp=None):
    sets = list(D.MAIN5)
    m5 = {s: {"total_exposure_rate": (sets_exp or {}).get(s, exposure), "full_rate": 0, "partial_rate": 0, "prf": {"f1": f1, "precision": f1, "recall": f1},
              "nonperson_fpr": (sets_fp or {}).get(s, fp)} for s in sets}
    safety = {"ambiguity_probe": {"nonperson_fpr": (sets_fp or {}).get("ambiguity_probe", fp)}}
    fp_sets = {s: (sets_fp or {}).get(s, fp) for s in D.FP_SETS}
    return {"main5": m5, "safety": safety, "overmerge": {"count": om},
            "macro": {"total_exposure": exposure, "exact_f1": f1, "nonperson_fpr": sum(fp_sets.values()) / len(fp_sets), "full_exposure": 0, "partial_exposure": 0, "precision": f1, "recall": f1}}


def test_gates_boundaries_inclusive():
    svc = _res(0.0600, 0.89, 0.20, 9)
    cands = {
        "pass_boundary": _res(0.0500, 0.88, 0.22, 9),                                   # 개선 -1.0%p, F1 -1.0%p, FP +2.0%p: 전부 경계값 -> 통과
        "fail_improve": _res(0.0501, 0.89, 0.20, 9),                                     # 개선 -0.99%p -> 요건 미달
        "fail_f1": _res(0.0400, 0.8799, 0.20, 9),                                        # F1 -1.01%p -> G3 탈락
        "fail_fp": _res(0.0400, 0.89, 0.2201, 9),                                        # FP +2.01%p -> G1 탈락
        "fail_overmerge": _res(0.0400, 0.89, 0.20, 10),                                  # 과잉 병합 증가 -> G2 탈락
        "fail_set_exposure": _res(0.0400, 0.89, 0.20, 9, sets_exp={"v7_namefreq": 0.0701}),  # 한 세트 +1.01%p -> G4 탈락
        "fail_worst_set_fp": _res(0.0400, 0.89, 0.20, 9, sets_fp={"v14_realistic": 0.2501}),   # 한 세트 +5.01%p -> G1 탈락
    }
    res = {"service": svc, **cands}
    out = D.select(res)["verdict"]
    assert out["pass_boundary"]["eligible"], out["pass_boundary"]
    assert not out["fail_improve"]["eligible"] and out["fail_improve"]["passes_gates"]
    assert not out["fail_f1"]["G3"] and not out["fail_fp"]["G1"] and not out["fail_overmerge"]["G2"] and not out["fail_set_exposure"]["G4"] and not out["fail_worst_set_fp"]["G1"]
    assert D.select({"service": svc})["chosen"] is None
    # 선정: 자격 있는 모델 중 매크로 노출 최저, 0.1%p 이내 동률이면 오탐 낮은 쪽
    res2 = {"service": svc, "a": _res(0.0400, 0.89, 0.21, 9), "b": _res(0.0405, 0.89, 0.19, 9), "c": _res(0.0300, 0.89, 0.20, 9)}
    assert D.select(res2)["chosen"] == "c"
    res3 = {"service": svc, "a": _res(0.0400, 0.89, 0.21, 9), "b": _res(0.0405, 0.89, 0.19, 9)}
    assert D.select(res3)["chosen"] == "b"


def test_one_char_exclusion_wrapper():
    import evaluate_r9_dev as D9
    r = D9.load_excluding_one_char(D.MAIN5["v7_namefreq"])
    assert len(r) == 2478 - 24 and all(e - s >= 2 for x in r for s, e in L.gold_person(x))
    assert D9.EXCLUDED["v7_namefreq.jsonl"] == 24


def test_no_sealed_path_in_dev_eval_code():
    for f in ("evaluate_r8_dev.py", "evaluate_r9_dev.py", "r8_eval_lib.py"):
        assert "sealed" not in (HERE / f).read_text(encoding="utf-8").lower().replace("sealed 평가셋은 열지 않는다", "").replace("봉인 평가셋은 열지 않는다", ""), f


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("통과:", t.__name__)
    print(f"{len(tests)}개 시험 통과")
