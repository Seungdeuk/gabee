"""blind_v6 사후 추가 분석 #2(2026-11-16): R1 시드7의 PERSON 완전미탐 40개 + 경계불일치 24개 원인 진단.

eval_integration.py / eval_style_set.py / eval_blind_v6_exact_prf.py 를 전혀 수정하지 않는 새 읽기 전용
스크립트다. 모델 가중치·운영 설정은 바꾸지 않고, 결과로 모델·규칙을 고치지도 않는다.

**NER_VALIDATION.md 40절(및 41절)에 기록된, style_v6_blind/README.md "모델당 정확히 1회" 규칙에 대한
두 번째 사용자 승인 예외다**(진단용, 1회성). 목적은 완전미탐/경계불일치 각 사례가 다음 중 무엇 때문인지
구분하는 것이다:
- 후보 미생성: 그 글자 구간에서 모델이 애초에 어떤 개체도 만들지 않음(토큰별 argmax 가 전부 'O')
- 다른 라벨로 오분류: 그 구간에 개체가 생겼지만 라벨이 PERSON/PERSON_ALIAS 가 아님(LOCATION/ORGANIZATION 등은
  ``LABEL_TO_KIND`` 정책상 애초에 내보내지 않는 라벨이라 이것도 여기 포함)
- 점수 임계값 탈락: PERSON 라벨 후보가 있었지만 평균 확률이 ``NER_MIN_SCORE``(0.5) 미만이라 ``merge_ner``가 버림
- 후처리 제거/경계 트리밍: 후보가 점수까지 통과했지만 ``merge_ner``의 트리밍(공백·구두점)·친족어·2글자 미만 제거로
  경계가 바뀌거나 사라짐

방법: ``ner.spans_for``(병합 전 1차 후보, 라벨·점수 그대로)와 ``ner.detect_with_ner``(최종, 서비스 경로)를
blind_v6 전체에 대해 1회 돌려 원인을 역추적한다. 분류 기준(완전미탐/경계불일치/정상)은 ``eval_style_set.py``
(coverage)·``eval_blind_v6_exact_prf.py``(exact)와 동일한 로직을 그대로 가져왔다(새로 설계하지 않음).

사용: ``python scripts/eval_blind_v6_miss_diagnosis.py <R1 시드7 모델 폴더> [--out 결과.json]``
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
EXPECT_FP12 = "c536eadeb5a1"


def integrated_predict(text: str, known_names: tuple[str, ...]) -> list:
    return ner.detect_with_ner(text, known_names)


def classify_gold(g: dict, preds: list) -> str:
    """eval_style_set.score_rows 와 동일한 coverage 분류(full/partial/none), PERSON 한정."""
    person_preds = [s for s in preds if s.kind is Kind.PERSON]
    cov: set[int] = set()
    for s in person_preds:
        overlap = range(max(s.start, g["start"]), min(s.end, g["end"]))
        if overlap:
            cov.update(overlap)
    n = g["end"] - g["start"]
    return "full" if len(cov) >= n else ("partial" if cov else "none")


def is_exact_match(g: dict, preds: list) -> bool:
    return any(s.kind is Kind.PERSON and s.start == g["start"] and s.end == g["end"] for s in preds)


def diagnose(text: str, g: dict, raw_spans: list) -> dict:
    overlapping = [
        s
        for s in raw_spans
        if max(s.start, g["start"]) < min(s.end, g["end"])
    ]
    person_overlap = [s for s in overlapping if s.label in ("PERSON", "PERSON_ALIAS")]
    if not overlapping:
        cause = "후보 미생성"
    elif not person_overlap:
        cause = f"다른 라벨로 오분류({'/'.join(sorted({s.label for s in overlapping}))})"
    elif all(s.score < ner.NER_MIN_SCORE for s in person_overlap):
        cause = "점수 임계값 탈락"
    else:
        cause = "후처리 제거/경계 트리밍(merge_ner)"
    return {
        "cause": cause,
        "raw_candidates": [
            {"label": s.label, "start": s.start, "end": s.end, "score": round(s.score, 4), "text": text[s.start : s.end]}
            for s in overlapping
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model_dir")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rows = [json.loads(line) for line in BLIND_V6.read_text(encoding="utf-8").splitlines() if line.strip()]

    ner.reset()
    settings.privacy_ner_mode = "required"
    settings.privacy_ner_model_dir = args.model_dir
    settings.privacy_ner_threads = 2
    status = ner.ner_status()
    fp12 = status["fingerprint"][:12]
    if fp12 != EXPECT_FP12:
        raise SystemExit(f"지문 불일치: got {fp12}, expect {EXPECT_FP12}")
    if not status["active"]:
        raise SystemExit("NER 엔진 비활성 상태")
    print(f"모델 지문 확인: {fp12}")

    complete_miss, boundary_mismatch = [], []
    for r in rows:
        text = r["text"]
        known = tuple(r.get("known_names", ()))
        raw = ner.spans_for(text) or []
        preds = integrated_predict(text, known)
        for g in r["spans"]:
            if g["kind"] != "PERSON":
                continue
            cov = classify_gold(g, preds)
            exact = is_exact_match(g, preds)
            if cov == "none":
                entry = {
                    "id": r["id"],
                    "category": r["category"],
                    "text": text,
                    "gold_name": text[g["start"] : g["end"]],
                    "gold_start": g["start"],
                    "gold_end": g["end"],
                    **diagnose(text, g, raw),
                }
                complete_miss.append(entry)
            elif not exact:
                entry = {
                    "id": r["id"],
                    "category": r["category"],
                    "text": text,
                    "gold_name": text[g["start"] : g["end"]],
                    "gold_start": g["start"],
                    "gold_end": g["end"],
                    "coverage": cov,
                    "final_prediction": [
                        {"start": s.start, "end": s.end, "text": text[s.start : s.end]}
                        for s in preds
                        if s.kind is Kind.PERSON and max(s.start, g["start"]) < min(s.end, g["end"])
                    ],
                    **diagnose(text, g, raw),
                }
                boundary_mismatch.append(entry)

    print(f"완전미탐(none): {len(complete_miss)}건")
    print(f"경계불일치(full/partial 이지만 exact 아님): {len(boundary_mismatch)}건")
    from collections import Counter

    print("완전미탐 원인 분포:", Counter(e["cause"] for e in complete_miss))
    print("경계불일치 원인 분포:", Counter(e["cause"] for e in boundary_mismatch))

    out = {"complete_miss": complete_miss, "boundary_mismatch": boundary_mismatch}
    out_path = args.out or (
        ROOT / "app" / "shared" / "privacy" / "eval" / "style_v6_blind" / "r1_s7_miss_diagnosis.json"
    )
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"결과 저장: {out_path}")


if __name__ == "__main__":
    main()
