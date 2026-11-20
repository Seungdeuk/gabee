"""R11 후보 선정 규칙(§7-4 r11-1.3)과 게이트 판정 시험. 합성 후보와 고정된 기준선 파일로 확인한다(B 학습 결과 없음)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import select_r11 as s  # noqa: E402

REF = Path(__file__).resolve().parents[3] / "docs" / "security" / "r11_validation"


def c(label, rec, f1, exp, seed=7, tm=0.15, fpr=0.03, prec=0.8, sd=0.03):
    return {"label": label, "seed": seed, "recall": rec, "f1": f1, "exposure": exp, "targets_macro": tm, "neg_fpr_macro": fpr, "precision": prec, "group_sd_sum": sd, "latency": None}


def test_dominated_candidate_removed_first():
    # A 가 B 를 모든 핵심 지표에서 앞선다 -> B 제거, A 선정(순위합이 아니라 우위 제거가 먼저)
    chosen, info = s.select_candidate([c("B", 0.74, 0.78, 0.17), c("A", 0.76, 0.80, 0.15)])
    assert chosen == "A" and "B" in info["dominated_removed"]


def test_non_dominated_use_unweighted_rank_sum():
    a = c("A", 0.80, 0.78, 0.17)  # Recall 1위
    b = c("B", 0.76, 0.82, 0.16)  # F1 1위, 노출 2위
    d = c("D", 0.77, 0.80, 0.14)  # 노출 1위, 나머지 2~3위
    chosen, info = s.select_candidate([a, b, d])
    assert info["dominated_removed"] == []
    # 순위: Recall A1 D3?(0.77>0.76) -> A1 D2 B3, F1 B1 D2 A3, 노출 D1 B2 A3 -> 합 A=1+3+3=7, B=3+1+2=6, D=2+2+1=5
    assert info["rank_sum"] == {"A": 7, "B": 6, "D": 5} and chosen == "D"


def test_tie_in_rank_sum_resolved_by_minimax_then_targets_then_seed():
    a = c("A", 0.80, 0.78, 0.15, seed=21, tm=0.14)
    b = c("B", 0.76, 0.82, 0.15, seed=7, tm=0.14)
    # A: R1 F2 E1(동률 1) = 4 / B: R2 F1 E1 = 4 -> 순위합 동률, minimax 도 같음(2) -> 표적 매크로 동률 -> 오탐 동률 -> Precision 동률 -> 군 SD 동률 -> 지연 -> 시드
    chosen, info = s.select_candidate([a, b])
    assert chosen == "B" and info["tiebreak_steps_used"][-1] == "seed"
    b2 = c("B", 0.76, 0.82, 0.15, seed=7, tm=0.16)
    assert s.select_candidate([a, b2])[0] == "A"  # 표적 매크로 노출이 낮은 A


def test_rounding_to_one_decimal_makes_tiny_differences_equal():
    a = c("A", 0.7601, 0.80, 0.15, seed=5)
    b = c("B", 0.7604, 0.80, 0.15, seed=3)  # 76.0 == 76.0 -> 같은 값, 지배 아님, 시드로 결정
    chosen, info = s.select_candidate([a, b])
    assert info["dominated_removed"] == [] and chosen == "B"


def test_no_candidates_returns_none():
    assert s.select_candidate([])[0] is None


def test_gates_smoke_on_fixed_baselines():
    ref = json.loads((REF / "r11_reference_baselines.json").read_text(encoding="utf-8"))
    rg = json.loads((REF / "r11_recall_gate_fixed.json").read_text(encoding="utf-8"))["thresholds"]
    thr = dict(ref["relative_gate_thresholds"])
    thr["_S0"] = ref["per_model"]["service"]
    g_s0 = s.gates(ref["per_model"]["service"], thr, rg)
    assert set(g_s0) == {"G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11", "R1", "R2", "R3", "R4"}
    assert g_s0["R2"] is False  # S0 자신은 S0 보다 Recall 이 엄격히 크지 않다
    assert g_s0["R1"] is False  # S0 Recall 이 R9F 평균 -δ 보다 낮다


def test_classification_is_research_only_and_marks_quality_sensitivity():
    assert s.classify(None)["classification"] is None
    c = s.classify("B-new-s7", {"quality_sensitive_models": {"B-new-s7": ["all_12_dev_flagged"]}})
    assert c["classification"] == s.RESEARCH_CLASSIFICATION and "교체 후보 자격 없음" in c["replacement_eligibility"]
    assert c["quality_sensitive"] is True and c["quality_sensitive_scenarios"] == ["all_12_dev_flagged"]
    assert s.classify("B-new-s7", {"quality_sensitive_models": {}})["quality_sensitive"] is False
    assert s.classify("B-new-s7")["quality_sensitive"] is False  # 민감도 결과가 없으면 표시하지 않지만 교체 자격 없음은 항상 붙는다
