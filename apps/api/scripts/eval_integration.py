"""통합 평가: 규칙(Baseline) / NER 단독 / 규칙+NER(서비스 병합 경로)를 평가용 test 분할에서 **한 번** 비교한다(외부 호출 없음).

주의(필독): 이 스크립트가 baseline_v2 의 **test 분할을 읽는 유일한 경로**다. test 는 학습·검증·모델 선택·임계값 결정에 쓰지 않았다.
결과를 보고 모델·규칙·병합을 고치지 않는다(고쳐야 하면 새 분할을 만든다). 그래서 ``--final`` 을 명시해야 실행된다.

세 방식
- A rule : ``detectors.detect`` 직접 호출(규칙 + 데이터의 known_names 가족 사전). NER 없음.
- B ner  : ``NerEngine.predict`` 의 NER 담당 5라벨(PERSON, PERSON_ALIAS, ADDRESS, LOCATION, ORGANIZATION) 구간을 그대로 낸다.
- C both : 서비스가 쓰는 ``ner.detect_with_ner``(규칙 우선 병합). LOCATION·ORGANIZATION 은 정책상 내보내지 않는다.

실행(apps/api, 환경변수 PRIVACY_NER_MODEL_DIR=<모델 폴더> PRIVACY_NER_MODE=required PRIVACY_NER_THREADS=2)::

    PYTHONPATH=. python scripts/eval_integration.py --final --expect-fingerprint 4ce93f7913e7

지표: exact/overlap 두 모드의 entity-level P/R/F1(라벨은 fine 12종 + mapped), 라벨별 FNR, 음성 문장 FPR, 보호 대상(mask_default=true)
재현율·정밀도, tags 별 재현율, 처리시간, 잔여 개인정보(예측 구간을 문자 단위로 가렸다고 가정).
"""

import argparse
import csv
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_pii import load, prf  # noqa: E402
from eval_pii_v2 import (  # noqa: E402
    FINE,
    LEGACY,
    V2_DIR,
    assign_fine,
    match_kind,
    new_counts,
    percentile,
    validate_dataset,
)

PRIVATE_DIR = ROOT / "data" / "private_eval" / "baseline_v2"
SAFE_RESULTS = ROOT / "app" / "shared" / "privacy" / "eval" / "results"
PRIVATE_RESULTS = ROOT / "data" / "private_eval" / "results"
MODES = ("exact", "overlap")
METHODS = ("A_rule", "B_ner", "C_rule_ner")
NER_LABELS = ("PERSON", "PERSON_ALIAS", "ADDRESS", "LOCATION", "ORGANIZATION")
NOT_EMITTED_BY_C = ("LOCATION", "ORGANIZATION")
MAPPED = [
    "PHONE",
    "EMAIL",
    "RRN",
    "CARD",
    "ACCOUNT",
    "SECRET",
    "ADDRESS",
    "PERSON",
    *NOT_EMITTED_BY_C,
]
NER_MAPPED = ["ADDRESS", "PERSON", *NOT_EMITTED_BY_C]
VIEW_KINDS = {"fine": FINE, "mapped": MAPPED}


def mapped_kind(fine: str) -> str:
    return LEGACY[fine] or fine


def to_fine_preds(text: str, spans) -> list[dict]:
    """탐지기 Span(Kind) 목록 -> 세분 라벨 예측 dict."""
    return [
        {
            "kind": assign_fine(s.kind.value, text[s.start : s.end]),
            "start": s.start,
            "end": s.end,
        }
        for s in spans
    ]


def ner_preds(spans) -> list[dict]:
    """NerSpan 목록 -> 예측 dict(NER 담당 5라벨만, 모델 라벨 그대로)."""
    return [
        {"kind": s.label, "start": s.start, "end": s.end}
        for s in spans
        if s.label in NER_LABELS and 0 <= s.start < s.end
    ]


def views_of(row: dict, preds: list[dict]) -> dict[str, tuple[list[dict], list[dict]]]:
    gold = row["spans"]
    return {
        "fine": (gold, preds),
        "mapped": (
            [{**g, "kind": mapped_kind(g["kind"])} for g in gold],
            [{**p, "kind": mapped_kind(p["kind"])} for p in preds],
        ),
    }


def _ov(a: dict, b: dict) -> bool:
    return min(a["end"], b["end"]) > max(a["start"], b["start"])


def score_row(row: dict, preds: list[dict]) -> dict:
    """한 문장의 지표 재료: counts[view][mode][kind], 보호 지표, 잔여 개인정보, 오류 목록(fine 관점)."""
    text = row["text"]
    views = views_of(row, preds)
    counts = {v: {m: {k: new_counts() for k in VIEW_KINDS[v]} for m in MODES} for v in VIEW_KINDS}
    errors = []
    for view, (gold_all, pred_all) in views.items():
        for mode in MODES:
            for kind in VIEW_KINDS[view]:
                g = [x for x in gold_all if x["kind"] == kind]
                p = [x for x in pred_all if x["kind"] == kind]
                pairs, missed, extra = match_kind(g, p, mode)
                c = counts[view][mode][kind]
                c["gold"] += len(g)
                c["pred"] += len(p)
                c["tp"] += len(pairs)
                c["fn"] += len(missed)
                c["fp"] += len(extra)
                if view != "fine" or mode != "overlap":
                    continue
                for gi in missed:
                    other = [x for x in pred_all if x["kind"] != kind and _ov(x, g[gi])]
                    errors.append(_err(row, "FN", kind, g[gi], other[0] if other else None))
                for pi in extra:
                    errors.append(_err(row, "FP", kind, None, p[pi]))
                for gi, pi in pairs:
                    if (g[gi]["start"], g[gi]["end"]) != (p[pi]["start"], p[pi]["end"]):
                        errors.append(_err(row, "BOUNDARY", kind, g[gi], p[pi]))
    gold_m, pred_m = views["mapped"]
    protect = [g for g in gold_m if g["mask_default"]]
    hit = sum(1 for g in protect if any(p["kind"] == g["kind"] and _ov(g, p) for p in pred_m))
    pred_hit = sum(1 for p in pred_m if any(p["kind"] == g["kind"] and _ov(g, p) for g in protect))
    policy = {
        "protect_gold": len(protect),
        "protect_hit": hit,
        "pred": len(pred_m),
        "pred_on_protect": pred_hit,
    }
    covered = [False] * len(text)
    for p in preds:
        for i in range(max(0, p["start"]), min(len(text), p["end"])):
            covered[i] = True
    res = {"full": 0, "partial": 0, "none": 0, "left_chars": 0, "gold_chars": 0}
    res_by_kind: dict[str, Counter] = {}
    for g in row["spans"]:
        if not g["mask_default"]:
            continue
        idx = [i for i in range(g["start"], g["end"]) if not text[i].isspace()]
        left = sum(1 for i in idx if not covered[i])
        cat = "full" if left == 0 else ("none" if left == len(idx) else "partial")
        res[cat] += 1
        res["left_chars"] += left
        res["gold_chars"] += len(idx)
        rk = res_by_kind.setdefault(mapped_kind(g["kind"]), Counter())
        rk[cat] += 1
        rk["left_chars"] += left
    return {
        "counts": counts,
        "policy": policy,
        "residual": res,
        "residual_by_kind": {k: dict(v) for k, v in res_by_kind.items()},
        "errors": errors,
        "flagged": bool(preds),
        "flagged_protectable": any(p["kind"] not in NOT_EMITTED_BY_C for p in preds),
        "n_gold": len(row["spans"]),
        "tags": row["tags"],
        "id": row["id"],
    }


def _err(row, etype, kind, gold, pred):
    text = row["text"]
    return {
        "id": row["id"],
        "error_type": etype,
        "kind": kind,
        "gold_text": text[gold["start"] : gold["end"]] if gold else "",
        "pred_kind": pred["kind"] if pred else "",
        "pred_text": text[pred["start"] : pred["end"]] if pred else "",
        "tags": "|".join(row["tags"]),
        "template_id": row["template_id"],
    }


def agg(records: list[dict], view: str, mode: str, kinds: list[str] | None = None) -> dict:
    tot = new_counts()
    for rec in records:
        for kind in kinds or VIEW_KINDS[view]:
            for key, val in rec["counts"][view][mode][kind].items():
                tot[key] += val
    p, r, f = prf(tot["tp"], tot["fp"], tot["fn"])
    return {
        **tot,
        "precision": p,
        "recall": r,
        "f1": f,
        "fnr": tot["fn"] / tot["gold"] if tot["gold"] else 0.0,
    }


def agg_policy(records: list[dict]) -> dict:
    t: Counter = Counter()
    for r in records:
        t.update(r["policy"])
    return {
        **t,
        "protect_recall": t["protect_hit"] / t["protect_gold"] if t["protect_gold"] else 0.0,
        "protect_precision": t["pred_on_protect"] / t["pred"] if t["pred"] else 0.0,
    }


def agg_fpr(records: list[dict]) -> dict:
    neg = [r for r in records if r["n_gold"] == 0]
    a = sum(1 for r in neg if r["flagged"])
    b = sum(1 for r in neg if r["flagged_protectable"])
    n = len(neg)
    return {
        "neg_sentences": n,
        "neg_flagged_any": a,
        "fpr_any": a / n if n else 0.0,
        "neg_flagged_excl_location_org": b,
        "fpr_excl_location_org": b / n if n else 0.0,
    }


def agg_residual(records: list[dict]) -> dict:
    t: Counter = Counter()
    by_kind: dict[str, Counter] = {}
    for r in records:
        t.update(r["residual"])
        for k, c in r["residual_by_kind"].items():
            by_kind.setdefault(k, Counter()).update(c)
    n = t["full"] + t["partial"] + t["none"]
    return {
        **t,
        "spans": n,
        "not_fully_masked": t["partial"] + t["none"],
        "full_rate": t["full"] / n if n else 0.0,
        "partial_rate": t["partial"] / n if n else 0.0,
        "none_rate": t["none"] / n if n else 0.0,
        "left_char_rate": t["left_chars"] / t["gold_chars"] if t["gold_chars"] else 0.0,
        "by_kind": {k: dict(v) for k, v in sorted(by_kind.items())},
    }


def tag_recalls(records: list[dict]) -> dict:
    out = {}
    for t in sorted({t for r in records for t in r["tags"]}):
        sub = [r for r in records if t in r["tags"]]
        m = agg(sub, "mapped", "overlap")
        p = agg_policy(sub)
        out[t] = {
            "sentences": len(sub),
            "gold": m["gold"],
            "recall_overlap": m["recall"] if m["gold"] else None,
            "precision_overlap": m["precision"] if m["pred"] else None,
            "protect_recall": p["protect_recall"] if p["protect_gold"] else None,
            "fp": m["fp"],
        }
    return out


def timing(fn, rows: list[dict], rounds: int) -> dict:
    """워밍업 1회 뒤 rounds 번 반복, 문장별 중앙값(ms)에서 평균·P95, 100자당 ms(중앙값 합 / 총 글자 * 100)."""
    for r in rows:
        fn(r)
    per = [[] for _ in rows]
    for _ in range(rounds):
        for i, r in enumerate(rows):
            t0 = time.perf_counter_ns()
            fn(r)
            per[i].append((time.perf_counter_ns() - t0) / 1e6)
    med = [statistics.median(x) for x in per]
    chars = sum(len(r["text"]) for r in rows)
    return {
        "rounds": rounds,
        "mean_ms": statistics.fmean(med),
        "p95_ms": percentile(med, 0.95),
        "max_ms": max(med),
        "ms_per_100_chars": sum(med) / chars * 100 if chars else 0.0,
    }


def summarize(records: list[dict]) -> dict:
    ner_only = NER_MAPPED
    return {
        "overall_fine": {m: agg(records, "fine", m) for m in MODES},
        "overall_mapped": {m: agg(records, "mapped", m) for m in MODES},
        "ner_labels_only_fine": {m: agg(records, "fine", m, list(NER_LABELS)) for m in MODES},
        "ner_labels_only_mapped": {m: agg(records, "mapped", m, ner_only) for m in MODES},
        "name_only_mapped_PERSON": {m: agg(records, "mapped", m, ["PERSON"]) for m in MODES},
        "per_kind_fine": {k: {m: agg(records, "fine", m, [k]) for m in MODES} for k in FINE},
        "per_kind_mapped": {k: {m: agg(records, "mapped", m, [k]) for m in MODES} for k in MAPPED},
        "protect": agg_policy(records),
        "fpr": agg_fpr(records),
        "tags": tag_recalls(records),
        "residual": agg_residual(records),
    }


def fmt(v):
    return round(v, 4) if isinstance(v, float) else v


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: fmt(r.get(k, "")) for k in cols})


METRIC_COLS = [
    "method",
    "view",
    "scope",
    "group",
    "mode",
    "gold",
    "pred",
    "tp",
    "fp",
    "fn",
    "precision",
    "recall",
    "f1",
    "fnr",
]
ERR_COLS = [
    "method",
    "id",
    "error_type",
    "kind",
    "gold_text",
    "pred_kind",
    "pred_text",
    "tags",
    "template_id",
]


def metric_rows(method: str, records: list[dict]) -> list[dict]:
    out = []
    for view, kinds in VIEW_KINDS.items():
        for mode in MODES:
            out.append(
                {
                    "method": method,
                    "view": view,
                    "scope": "overall",
                    "group": "all",
                    "mode": mode,
                    **agg(records, view, mode),
                }
            )
            for k in kinds:
                out.append(
                    {
                        "method": method,
                        "view": view,
                        "scope": "kind",
                        "group": k,
                        "mode": mode,
                        **agg(records, view, mode, [k]),
                    }
                )
    for t in sorted({t for r in records for t in r["tags"]}):
        sub = [r for r in records if t in r["tags"]]
        for mode in MODES:
            out.append(
                {
                    "method": method,
                    "view": "mapped",
                    "scope": "tag",
                    "group": t,
                    "mode": mode,
                    **agg(sub, "mapped", mode),
                }
            )
    return out


def top_errors(errors: list[dict], n: int = 15) -> list[dict]:
    c = Counter(
        (e["error_type"], e["kind"], e["tags"]) for e in errors if e["error_type"] != "BOUNDARY"
    )
    return [
        {"error_type": a, "kind": b, "tags": t, "count": k} for (a, b, t), k in c.most_common(n)
    ]


def run_set(
    name: str, directory: Path, rounds: int, engine, ner_mod, detect, expect_fp: str
) -> dict:
    rows = load(directory / "test.jsonl")  # test 분할을 읽는 유일한 지점
    problems = validate_dataset(rows)
    if problems or {r["split"] for r in rows} != {"test"}:
        raise SystemExit(f"[{name}] 형식 오류: {problems[:5]}")
    print(f"[{name}] test 문장 {len(rows)}개 (한 번만 평가)")

    def a(r):
        return detect(r["text"], tuple(r["known_names"]))

    def b(r):
        return engine.predict(r["text"])

    def c(r):
        ner_mod._cache.clear()  # 시간 측정 때 캐시 적중을 막는다
        return ner_mod.detect_with_ner(r["text"], tuple(r["known_names"]))

    ner_mod._cache.clear()
    preds = {
        "A_rule": [to_fine_preds(r["text"], a(r)) for r in rows],
        "B_ner": [ner_preds(b(r)) for r in rows],
        "C_rule_ner": [to_fine_preds(r["text"], c(r)) for r in rows],
    }
    # 서비스 C 가 실제로 NER 을 썼는지(규칙과 다른 결과가 있는지)도 기록
    c_extra = sum(1 for x, y in zip(preds["A_rule"], preds["C_rule_ner"], strict=True) if x != y)
    result: dict = {
        "dataset": name,
        "sentences": len(rows),
        "negative_sentences": sum(1 for r in rows if not r["spans"]),
        "c_differs_from_a_sentences": c_extra,
        "methods": {},
    }
    errs_all, mrows = [], []
    for m in METHODS:
        recs = [score_row(r, p) for r, p in zip(rows, preds[m], strict=True)]
        s = summarize(recs)
        fn = {"A_rule": a, "B_ner": b, "C_rule_ner": c}[m]
        s["timing"] = timing(fn, rows, rounds)
        errs = [{"method": m, **e} for rec in recs for e in rec["errors"]]
        s["error_counts"] = {
            t: sum(1 for e in errs if e["error_type"] == t) for t in ("FN", "FP", "BOUNDARY")
        }
        s["top_errors"] = top_errors(errs)
        s["error_examples"] = [e for e in errs if e["error_type"] != "BOUNDARY"][
            :0
        ]  # 값은 요약 JSON 에 싣지 않는다(CSV 에만)
        result["methods"][m] = s
        errs_all += errs
        mrows += metric_rows(m, recs)
    result["_errors"] = errs_all
    result["_metric_rows"] = mrows
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--final", action="store_true", help="test 분할 최종 평가임을 확인(필수)")
    ap.add_argument("--expect-fingerprint", default="", help="모델 지문 앞부분(다르면 중단)")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--summary-json", type=Path, default=None)
    ap.add_argument("--no-private", action="store_true")
    args = ap.parse_args()
    if not args.final:
        print("test 분할은 최종 평가에서 한 번만 읽는다. --final 을 명시하세요.")
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import app

    print(f"app 경로: {Path(app.__file__).resolve()}")
    from app.shared.privacy import ner as ner_mod
    from app.shared.privacy.detectors import detect

    st = ner_mod.ner_status()
    print(f"ner_status: mode={st['mode']} active={st['active']} fp={st['fingerprint'][:12]}")
    if st["mode"] != "required" or not st["active"]:
        print("NER 가 켜져 있지 않아 평가를 중단한다.")
        return 1
    if args.expect_fingerprint and not st["fingerprint"].startswith(args.expect_fingerprint[:12]):
        print("모델 지문이 기대와 다르다. 중단.")
        return 1
    engine = ner_mod._get_engine(ner_mod._config())

    sets = [("safe_fixture", V2_DIR, SAFE_RESULTS)]
    if not args.no_private and (PRIVATE_DIR / "test.jsonl").exists():
        sets.append(("private_original", PRIVATE_DIR, PRIVATE_RESULTS))
    summary = {"model_fingerprint12": st["fingerprint"][:12], "datasets": {}}
    for name, directory, out in sets:
        res = run_set(
            name, directory, args.rounds, engine, ner_mod, detect, args.expect_fingerprint
        )
        errs, mrows = res.pop("_errors"), res.pop("_metric_rows")
        write_csv(out / f"integration_{name}_metrics.csv", mrows, METRIC_COLS)
        write_csv(out / f"integration_{name}_errors.csv", errs, ERR_COLS)
        (out / f"integration_{name}_summary.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=1, default=fmt),
            encoding="utf-8",
            newline="\n",
        )
        summary["datasets"][name] = res
        for m, s in res["methods"].items():
            o, e = s["overall_fine"]["overlap"], s["overall_fine"]["exact"]
            print(
                f"  {m}: fine overlap P/R/F1 {o['precision']:.3f}/{o['recall']:.3f}/{o['f1']:.3f} "
                f"exact F1 {e['f1']:.3f} | 보호재현 {s['protect']['protect_recall']:.3f} "
                f"FPR {s['fpr']['fpr_any']:.3f} | {s['timing']['mean_ms']:.2f}ms"
            )
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=1, default=fmt),
            encoding="utf-8",
            newline="\n",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
