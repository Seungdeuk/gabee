"""blind_v6 사후 추가 분석(2026-11-14): entity-level EXACT-MATCH micro P/R/F1.

eval_integration.py / eval_style_set.py 를 전혀 수정하지 않는 새 읽기 전용 스크립트다. 목적은
style_v6_blind/blind_v6.jsonl 에서 "완전미탐률"(coverage 기준 full/partial/none, eval_style_set.py)로만
측정됐던 서비스 모델(v2b)과 R1 시드7을, eval_integration.py 와 동일한 "exact(시작·끝 정확히 일치)
entity-level micro P/R/F1" 기준으로도 측정하기 위한 것이다.

**이 실행은 docs/security/NER_VALIDATION.md 40절에 기록된, style_v6_blind/README.md "모델당 정확히 1회"
규칙에 대한 사용자 승인 예외다**(사후 추가 분석, 1회성). 기존 모델 가중치·설정은 바꾸지 않고, 결과로 모델·규칙을
고치지 않는다. 다시 실행하지 않는다(이미 실행됨 — 결과는 app/shared/privacy/eval/style_v6_blind/
exact_prf_postselection_analysis.json).

측정 대상: PERSON 라벨만(blind_v6 의 정답 구간 440개 전부 PERSON). 두 경로를 구분한다.
- ner_only: 규칙 없이 NER 단독(eval_style_set.py 의 ner_only_predict 와 동일한 로직)
- integrated: 서비스가 실제로 쓰는 ner.detect_with_ner(규칙+NER 병합, known_names 는 blind_v6 설계상 전부 비어 있음)

TP/FP/FN(entity-level, exact): 정답 PERSON 구간과 예측 PERSON 구간의 (start, end) 가 정확히 같을 때만
매칭(1:1). 매칭된 정답=TP, 매칭 안 된 정답=FN, 매칭 안 된 예측(비이름 문장의 예측 포함)=FP.

사용: ``python scripts/eval_blind_v6_exact_prf.py <서비스 모델 폴더> <R1 시드7 모델 폴더> [--out 결과.json]``
(apps/api 에서, 두 모델 폴더 모두 로컬에 있어야 한다 — 지문을 model_card.json 기대값과 대조해 확인한다)
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app.shared.config import settings  # noqa: E402
from app.shared.privacy import ner  # noqa: E402
from app.shared.privacy.types import Kind  # noqa: E402

BLIND_V6 = ROOT / "app" / "shared" / "privacy" / "eval" / "style_v6_blind" / "blind_v6.jsonl"

EXPECT_FP12 = {
    "service": "46210943c45f",
    "r1_s7": "c536eadeb5a1",
}


def ner_only_predict(text: str, known_names: tuple[str, ...]) -> list:
    raw = ner.spans_for(text) or []
    return ner.merge_ner(text, [], raw)


def integrated_predict(text: str, known_names: tuple[str, ...]) -> list:
    return ner.detect_with_ner(text, known_names)


def score(rows: list[dict], predict) -> dict:
    tp = fp = fn = 0
    neg_sentences = 0
    neg_flagged = 0
    fp_examples: list[list] = []
    fn_examples: list[list] = []
    for r in rows:
        text = r["text"]
        preds = [
            (s.start, s.end)
            for s in predict(text, tuple(r.get("known_names", ())))
            if s.kind is Kind.PERSON
        ]
        gold = [(g["start"], g["end"]) for g in r["spans"] if g["kind"] == "PERSON"]
        if not gold:
            neg_sentences += 1
            if preds:
                neg_flagged += 1
            fp += len(preds)
            if preds and len(fp_examples) < 8:
                fp_examples.append(["negative_sentence", text, [text[a:b] for a, b in preds]])
            continue
        remaining_preds = list(preds)
        for g in gold:
            if g in remaining_preds:
                tp += 1
                remaining_preds.remove(g)
            else:
                fn += 1
                if len(fn_examples) < 8:
                    fn_examples.append([text, text[g[0] : g[1]]])
        fp += len(remaining_preds)
        if remaining_preds and len(fp_examples) < 8:
            fp_examples.append(["boundary_or_spurious", text, [text[a:b] for a, b in remaining_preds]])
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "neg_sentences": neg_sentences,
        "neg_flagged": neg_flagged,
        "fp_examples": fp_examples,
        "fn_examples": fn_examples,
    }


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
    print(f"\n== {model_key} (지문 {fp12}) ==")

    out = {"fingerprint12": fp12}
    for method_key, predict in (("ner_only", ner_only_predict), ("integrated", integrated_predict)):
        ner._cache.clear()
        res = score(rows, predict)
        out[method_key] = res
        print(
            f"  {method_key:10s} TP={res['tp']:3d} FP={res['fp']:3d} FN={res['fn']:3d} "
            f"P={res['precision']:.4f} R={res['recall']:.4f} F1={res['f1']:.4f} "
            f"| 비이름 오탐 {res['neg_flagged']}/{res['neg_sentences']}"
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("service_model_dir")
    ap.add_argument("r1_model_dir")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rows = [json.loads(line) for line in BLIND_V6.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"blind_v6 문장 수: {len(rows)} (정답 PERSON 구간: {sum(len(r['spans']) for r in rows)})")

    out = {
        "service": run_model("service", args.service_model_dir, rows),
        "r1_s7": run_model("r1_s7", args.r1_model_dir, rows),
    }

    out_path = args.out or (
        ROOT / "app" / "shared" / "privacy" / "eval" / "style_v6_blind" / "exact_prf_postselection_analysis.json"
    )
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
