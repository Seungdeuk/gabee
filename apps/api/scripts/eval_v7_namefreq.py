"""v7 이름빈도 평가셋(style_v7_namefreq)에서 서비스 모델 vs R1 시드7 비교(읽기 전용, 서비스 경로만).

eval_integration.py/eval_style_set.py/eval_blind_v6_*.py 를 전혀 수정하지 않는 새 스크립트다. blind_v6 를
쓰지 않는다(새로 만든 v7 이다). 모델 가중치·운영 설정은 바꾸지 않는다.

측정(entity-level, exact=시작·끝 정확히 일치, micro):
- 전체 Exact-match Precision/Recall/F1
- 완전미탐률(coverage 기준 none), 경계불일치율(coverage full/partial 이지만 exact 아님)
- 빈도(고빈도/저빈도)·성씨 유무·조사 유무별 breakdown
- 비인명 문장 오탐률

사용: ``python scripts/eval_v7_namefreq.py <서비스 모델 폴더> <R1 모델 폴더> [--out 결과.json]``
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app.shared.config import settings  # noqa: E402
from app.shared.privacy import ner  # noqa: E402
from app.shared.privacy.types import Kind  # noqa: E402

V7 = ROOT / "app" / "shared" / "privacy" / "eval" / "style_v7_namefreq" / "v7_namefreq.jsonl"
EXPECT_FP12 = {"service": "46210943c45f", "r1_s7": "c536eadeb5a1"}


def classify(g: dict, preds: list) -> tuple[str, bool]:
    person_preds = [s for s in preds if s.kind is Kind.PERSON]
    cov: set[int] = set()
    exact = False
    for s in person_preds:
        if s.start == g["start"] and s.end == g["end"]:
            exact = True
        overlap = range(max(s.start, g["start"]), min(s.end, g["end"]))
        if overlap:
            cov.update(overlap)
    n = g["end"] - g["start"]
    coverage = "full" if len(cov) >= n else ("partial" if cov else "none")
    bucket = "정확탐지" if exact else ("완전미탐" if coverage == "none" else "경계불일치")
    return bucket, exact


def run_model(model_key: str, model_dir: str, rows: list[dict]) -> dict:
    ner.reset()
    settings.privacy_ner_mode = "required"
    settings.privacy_ner_model_dir = model_dir
    settings.privacy_ner_threads = 2
    status = ner.ner_status()
    fp12 = status["fingerprint"][:12]
    expect = EXPECT_FP12.get(model_key)
    if expect and fp12 != expect:
        raise SystemExit(f"[{model_key}] 지문 불일치: got {fp12}, expect {expect}")
    if not status["active"]:
        raise SystemExit(f"[{model_key}] NER 엔진 비활성 상태")
    ner._cache.clear()

    tp = fp = fn = 0
    bucket_counts: dict[str, int] = defaultdict(int)
    by_band: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_surname: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_particle: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    neg_sentences = neg_flagged = 0

    for r in rows:
        text = r["text"]
        preds = ner.detect_with_ner(text, tuple(r.get("known_names", ())))
        person_preds = [s for s in preds if s.kind is Kind.PERSON]
        if not r["spans"]:
            neg_sentences += 1
            if person_preds:
                neg_flagged += 1
            fp += len(person_preds)
            continue
        g = r["spans"][0]
        bucket, exact = classify(g, preds)
        bucket_counts[bucket] += 1
        # eval_blind_v6_exact_prf.py 와 동일한 TP/FP/FN 정의: (start,end) 정확히 같은 예측 1개만 TP,
        # 나머지 예측(겹치든 안 겹치든)은 전부 FP.
        exact_idx = next(
            (i for i, s in enumerate(person_preds) if s.start == g["start"] and s.end == g["end"]),
            None,
        )
        if exact_idx is not None:
            tp += 1
            fp += len(person_preds) - 1
        else:
            fn += 1
            fp += len(person_preds)

        by_band[r["freq_band"]]["total"] += 1
        by_band[r["freq_band"]][bucket] += 1
        surname_key = "있음" if r["has_surname"] else "없음"
        by_surname[surname_key]["total"] += 1
        by_surname[surname_key][bucket] += 1
        particle_key = "있음" if r["has_particle"] else "없음"
        by_particle[particle_key]["total"] += 1
        by_particle[particle_key][bucket] += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    total_person = tp + fn
    return {
        "fingerprint12": fp12,
        "person_total": total_person,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "bucket_counts": dict(bucket_counts),
        "완전미탐률": round(bucket_counts["완전미탐"] / total_person, 4),
        "경계불일치율": round(bucket_counts["경계불일치"] / total_person, 4),
        "노출_1건이상_비율": round((bucket_counts["정확탐지"] + bucket_counts["경계불일치"]) / total_person, 4),
        "by_freq_band": {
            k: {**v, "exact_recall": round(v["정확탐지"] / v["total"], 4), "경계오류율": round(v["경계불일치"] / v["total"], 4)}
            for k, v in by_band.items()
        },
        "by_surname": {
            k: {**v, "exact_recall": round(v["정확탐지"] / v["total"], 4), "경계오류율": round(v["경계불일치"] / v["total"], 4)}
            for k, v in by_surname.items()
        },
        "by_particle": {
            k: {**v, "exact_recall": round(v["정확탐지"] / v["total"], 4), "경계오류율": round(v["경계불일치"] / v["total"], 4)}
            for k, v in by_particle.items()
        },
        "neg_sentences": neg_sentences,
        "neg_flagged": neg_flagged,
        "neg_fpr": round(neg_flagged / neg_sentences, 4) if neg_sentences else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("service_model_dir")
    ap.add_argument("r1_model_dir")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rows = [json.loads(line) for line in V7.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"v7 문장 {len(rows)}개 (PERSON {sum(len(r['spans']) for r in rows)}개)")

    out = {
        "service": run_model("service", args.service_model_dir, rows),
        "r1_s7": run_model("r1_s7", args.r1_model_dir, rows),
    }
    for key, res in out.items():
        print(
            f"{key}: P={res['precision']} R={res['recall']} F1={res['f1']} "
            f"완전미탐률={res['완전미탐률']} 경계불일치율={res['경계불일치율']} 비인명FPR={res['neg_fpr']}"
        )

    out_path = args.out or (
        ROOT / "app" / "shared" / "privacy" / "eval" / "style_v7_namefreq" / "results_service_vs_r1s7.json"
    )
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {out_path}")


if __name__ == "__main__":
    main()
