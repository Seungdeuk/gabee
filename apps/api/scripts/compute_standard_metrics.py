"""GaBee NER 표준 평가 지표(7종 + 전체노출률) 계산 — 읽기 전용, 재학습 없음.

NER_VALIDATION.md 55절에서 정한 표준 지표를 임의 평가셋 + 모델 목록에 대해 계산한다.
원시 경로(`ner.spans_for`, merge_ner 이전)와 최종 경로(`ner.detect_with_ner`, 실제 서비스가 쓰는
규칙+NER 통합 결과 = 실제 전송 문자열 기준)를 분리해서 낸다. 노출률(완전/부분/가림)은 정의상
최종 경로에서만 의미가 있다(원시 경로는 "전송 문자열"이 아니므로 계산하지 않는다).

ner.py·detectors.py·모델·DB·설정 전부 미수정, 평가셋 파일 미수정, 외부 LLM 미호출, 재학습 없음.
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


def load_rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def gold_spans(row: dict) -> list[tuple[int, int]]:
    return [(sp["start"], sp["end"]) for sp in row.get("spans", []) if sp.get("kind") in ("PERSON", "PERSON_ALIAS")]


def covered(spans, g: tuple[int, int]) -> set[int]:
    cov: set[int] = set()
    for s in spans:
        if s.kind is Kind.PERSON:
            cov.update(range(max(s.start, g[0]), min(s.end, g[1])))
    return cov


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * p * r / (p + r)) if p and r and (p + r) else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1}


def eval_rows(rows: list[dict], *, sub_tag: str | None = None) -> dict:
    rows = [r for r in rows if sub_tag is None or r.get(sub_tag[0]) == sub_tag[1]]
    raw_tp = raw_fp = raw_fn = 0
    fin_tp = fin_fp = fin_fn = 0
    full_exp = part_exp = full_mask = 0
    pos_total = 0
    neg_total = neg_flagged = 0

    for r in rows:
        text = r["text"]
        golds = gold_spans(r)
        raw = ner.spans_for(text) or []
        final = ner.detect_with_ner(text, ())
        raw_person = [(s.start, s.end) for s in raw if s.label in ("PERSON", "PERSON_ALIAS")]
        final_person = [(s.start, s.end) for s in final if s.kind is Kind.PERSON]

        if golds:
            pos_total += 1
            for g in golds:
                n = g[1] - g[0]
                raw_tp += int(g in raw_person)
                fin_tp += int(g in final_person)
                leaked = n - len(covered(final, g))
                if leaked >= n:
                    full_exp += 1
                elif leaked > 0:
                    part_exp += 1
                else:
                    full_mask += 1
            raw_fn += sum(1 for g in golds if g not in raw_person)
            fin_fn += sum(1 for g in golds if g not in final_person)
            raw_fp += sum(1 for p in raw_person if p not in golds)
            fin_fp += sum(1 for p in final_person if p not in golds)
        else:
            neg_total += 1
            neg_flagged += int(bool(final_person))

    n_pos = full_exp + part_exp + full_mask
    return {
        "pos_sentences": pos_total, "neg_sentences": neg_total,
        "raw_prf": prf(raw_tp, raw_fp, raw_fn),
        "final_prf": prf(fin_tp, fin_fp, fin_fn),
        "exposure": {
            "full_exposure": full_exp, "partial_exposure": part_exp, "fully_masked": full_mask,
            "full_exposure_rate": round(full_exp / n_pos, 4) if n_pos else None,
            "partial_exposure_rate": round(part_exp / n_pos, 4) if n_pos else None,
            "fully_masked_rate": round(full_mask / n_pos, 4) if n_pos else None,
            "total_exposure_rate": round((full_exp + part_exp) / n_pos, 4) if n_pos else None,
        },
        "nonperson_fpr": round(neg_flagged / neg_total, 4) if neg_total else None,
    }


def run_model(model_key: str, model_dir: str, expect_fp12: str | None, datasets: dict[str, Path], subtags: dict[str, tuple]) -> dict:
    ner.reset()
    settings.privacy_ner_mode = "required"
    settings.privacy_ner_model_dir = model_dir
    settings.privacy_ner_threads = 2
    status = ner.ner_status()
    fp12 = status["fingerprint"][:12]
    if expect_fp12 and fp12 != expect_fp12:
        raise SystemExit(f"[{model_key}] 지문 불일치: got {fp12}, expected {expect_fp12}")
    ner._cache.clear()
    out = {"fingerprint12": fp12}
    for name, path in datasets.items():
        rows = load_rows(path)
        out[name] = eval_rows(rows)
        tag = subtags.get(name)
        if tag:
            out[f"{name}__{tag[1]}"] = eval_rows(rows, sub_tag=tag)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--service", required=True)
    ap.add_argument("--r3-candidate", required=True)
    ap.add_argument("--r4-candidate", required=True)
    ap.add_argument("--service-fp12", default="46210943c45f")
    ap.add_argument("--r3-fp12", default="14f297c7d5f5")
    ap.add_argument("--r4-fp12", default="56249473d8d9")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    eval_root = ROOT / "app" / "shared" / "privacy" / "eval"
    datasets = {
        "v10_locked": eval_root / "style_v10_locked" / "v10_locked.jsonl",
        "ambiguity_probe_48": eval_root / "style_ambiguity_probe" / "ambiguity_probe.jsonl",
    }
    subtags = {}  # category-level cuts are derived separately below for v10

    out = {
        "service": run_model("service", a.service, a.service_fp12, datasets, subtags),
        "r3_candidate": run_model("r3_candidate", a.r3_candidate, a.r3_fp12, datasets, subtags),
        "r4_candidate": run_model("r4_candidate", a.r4_candidate, a.r4_fp12, datasets, subtags),
    }

    # v10 문형별/유형별 세부 (category, word_type)
    v10_rows = load_rows(datasets["v10_locked"])
    categories = sorted({r.get("category") for r in v10_rows if r.get("category") and r.get("category") != "nonperson" and r.get("category") != "background"})
    word_types = sorted({r.get("word_type") for r in v10_rows if r.get("word_type")})
    for key, model_dir, fp12 in (("service", a.service, a.service_fp12), ("r3_candidate", a.r3_candidate, a.r3_fp12), ("r4_candidate", a.r4_candidate, a.r4_fp12)):
        ner.reset()
        settings.privacy_ner_mode = "required"
        settings.privacy_ner_model_dir = model_dir
        settings.privacy_ner_threads = 2
        ner.ner_status()
        ner._cache.clear()
        out[key]["v10_by_category"] = {c: eval_rows([r for r in v10_rows if r.get("category") == c]) for c in categories}
        out[key]["v10_by_word_type"] = {wt: eval_rows([r for r in v10_rows if r.get("word_type") == wt]) for wt in word_types}

    a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for key in out:
        v10 = out[key]["v10_locked"]
        print(f"{key}: fp12={out[key]['fingerprint12']}")
        print(f"  raw P/R/F1 = {v10['raw_prf']['precision']}/{v10['raw_prf']['recall']}/{v10['raw_prf']['f1']}")
        print(f"  final P/R/F1 = {v10['final_prf']['precision']}/{v10['final_prf']['recall']}/{v10['final_prf']['f1']}")
        print(f"  exposure = {v10['exposure']}")
        print(f"  nonperson_fpr(v10 전체) = {v10['nonperson_fpr']}")
        amb = out[key]["ambiguity_probe_48"]
        print(f"  nonperson_fpr(48절 중의성) = {amb['nonperson_fpr']}")
    print(f"\n저장: {a.out}")


if __name__ == "__main__":
    main()
