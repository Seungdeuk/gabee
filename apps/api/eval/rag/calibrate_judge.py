"""판정 모델 검정: 공개 리더보드의 시스템 답과 O/X(LLM 4종 투표)를 우리 판정 모델과 비교한다.

평가 데이터를 쓰지만 우리 시스템의 답은 보지 않는다. 표본은 시드 고정이고 O/X 를 고르게 뽑는다.

    PYTHONPATH=. python eval/rag/calibrate_judge.py --source <rag_eval_data> --n 120
    PYTHONPATH=. python eval/rag/calibrate_judge.py --cross    # 두 번째 판정자(Opus)와 표본 30건 교차 검정 → judge_cross.json
"""

import argparse
import csv
import json
import random
from pathlib import Path

import answer_eval as ev
import retrieval_eval as public

SEED = 20261111
CROSS_SEED = 20261112
CROSS_N = 30
FAITH_N = 8
FAITH_MAX_CHARS = 5000
FAMILY_REJUDGED = "eval/rag/runs/answer_dev_family_baseline_v2.partial.jsonl"
PUBLIC_PARTIAL = "eval/rag/runs/answer_dev_baseline.partial.jsonl"
CROSS_NOTE = (
    "일치율은 표본 30건에서 두 판정자의 이진(O/X) 라벨이 같은 비율이다. 모집단 정확도도 Opus 의 정답률도 아니며, "
    "두 판정자가 같은 방향으로 틀리는 경우는 잡지 못한다. 가족 dev 행에는 근거 글(context)이 저장돼 있지 않아 "
    "근거 판정만 근거 글이 저장된 공개 dev 행(글 5,000자 이하) 8건으로 했다(비용 상한 때문에 표본이 작다)."
)


def _agree(pairs: list[tuple[object, object]]) -> dict:
    n = len(pairs)
    same = sum(1 for a, b in pairs if a == b)
    return {"n": n, "agree": same, "rate": round(same / n, 4) if n else None}


def _doc_claims(verdict: dict) -> list[dict]:
    return [c for c in verdict.get("claims", []) if isinstance(c, dict) and c.get("kind") != "meta"]


def _number_status(verdict: dict, gold: str) -> str:
    if not ev.has_gold_value(gold):
        return "no_gold_value"
    status = verdict.get("number_status")
    return status if status in ev.NUMBER_STATUSES else "no_value"


def cross_main(args) -> None:
    """가족 dev 재판정 행에서 30건을 뽑아 Sonnet(저장된 v2 판정)과 Opus 판정을 견준다."""
    ev.judge_budget_usd = args.max_usd
    rng = random.Random(CROSS_SEED)
    rows, _ = ev.read_partial(Path(FAMILY_REJUDGED))
    ok = [r for r in rows.values() if r.get("ai") and r.get("v") == ev.SCORING_VERSION]
    answerable = [r for r in ok if r["kind"] == "answerable"]
    numeric = [r for r in answerable if ev.has_gold_value(r["answer_gold"])]
    plain = [r for r in answerable if not ev.has_gold_value(r["answer_gold"])]
    no_ans = [r for r in ok if r["kind"] == "no_answer"]
    sample = rng.sample(numeric, 15) + rng.sample(plain, 5) + rng.sample(no_ans, 10)
    out_rows = []
    if args.cross_out.exists():  # 가족 표본 판정은 이미 했으면 다시 비용을 쓰지 않는다
        out_rows = json.loads(args.cross_out.read_text("utf-8")).get("rows", [])
        sample = []
    for r in sample:
        if ev.METER.cost() > args.max_usd - 0.05:  # 상한에 닿으면 여기까지만 쓴다
            break
        if r["kind"] == "answerable":
            v = ev.judge_correct(
                r["question"], r["answer_gold"], r["answer"], ev.SECOND_JUDGE_MODEL
            )
            out_rows.append(
                {
                    "qid": r["qid"],
                    "kind": "answerable",
                    "sonnet": {
                        "correct": r["correct"],
                        "abstained": r["abstained"],
                        "number_status": r["number_status"],
                    },
                    "opus": {
                        "correct": bool(v.get("correct")),
                        "abstained": bool(v.get("abstained")),
                        "number_status": _number_status(v, r["answer_gold"]),
                    },
                }
            )
        else:
            v = ev.judge_abstain(r["question"], r["answer"], ev.SECOND_JUDGE_MODEL)
            abstained, other = bool(v.get("abstained")), bool(v.get("gave_other_value"))
            out_rows.append(
                {
                    "qid": r["qid"],
                    "kind": "no_answer",
                    "sonnet": {
                        "abstained": r["abstained"],
                        "abstain_status": r["abstain_status"],
                    },
                    "opus": {
                        "abstained": abstained,
                        "abstain_status": ev.abstain_status(abstained, other, r.get("tools", [])),
                    },
                }
            )
    ans = [o for o in out_rows if o["kind"] == "answerable"]
    num = [o for o in ans if o["sonnet"]["number_status"] != "no_gold_value"]
    noa = [o for o in out_rows if o["kind"] == "no_answer"]

    public_rows, _ = ev.read_partial(Path(PUBLIC_PARTIAL))
    pool = [
        r
        for r in public_rows.values()
        if r["kind"] == "answerable"
        and r.get("ai")
        and 0 < len(r.get("context", "")) <= FAITH_MAX_CHARS
    ]
    faith_rows = []
    for r in rng.sample(pool, min(FAITH_N, len(pool))):
        if ev.METER.cost() > args.max_usd - 0.05:
            break
        s_v = ev.judge_faith(r["context"], r["answer"])
        o_v = ev.judge_faith(r["context"], r["answer"], ev.SECOND_JUDGE_MODEL)
        faith_rows.append(
            {
                "qid": r["qid"],
                "sonnet": {
                    "claims_doc": len(_doc_claims(s_v)),
                    "unsupported": sum(1 for c in _doc_claims(s_v) if not c.get("supported")),
                },
                "opus": {
                    "claims_doc": len(_doc_claims(o_v)),
                    "unsupported": sum(1 for c in _doc_claims(o_v) if not c.get("supported")),
                },
            }
        )
    summary = {
        "note": CROSS_NOTE,
        "judges": {"first": ev.JUDGE_MODEL, "second": ev.SECOND_JUDGE_MODEL},
        "n_family_sample": len(out_rows),
        "n_faith_sample": len(faith_rows),
        "correct": _agree([(o["sonnet"]["correct"], o["opus"]["correct"]) for o in ans]),
        "answerable_abstained": _agree(
            [(o["sonnet"]["abstained"], o["opus"]["abstained"]) for o in ans]
        ),
        "number_status_exact": _agree(
            [(o["sonnet"]["number_status"], o["opus"]["number_status"]) for o in num]
        ),
        "number_status_correct_vs_not": _agree(
            [
                (o["sonnet"]["number_status"] == "correct", o["opus"]["number_status"] == "correct")
                for o in num
            ]
        ),
        "no_answer_abstained": _agree(
            [(o["sonnet"]["abstained"], o["opus"]["abstained"]) for o in noa]
        ),
        "no_answer_status_exact": _agree(
            [(o["sonnet"]["abstain_status"], o["opus"]["abstain_status"]) for o in noa]
        ),
        "faith_has_unsupported": _agree(
            [(f["sonnet"]["unsupported"] > 0, f["opus"]["unsupported"] > 0) for f in faith_rows]
        ),
        "faith_unsupported_count_exact": _agree(
            [(f["sonnet"]["unsupported"], f["opus"]["unsupported"]) for f in faith_rows]
        ),
        "faith_claims_doc_total": {
            "sonnet": sum(f["sonnet"]["claims_doc"] for f in faith_rows),
            "opus": sum(f["opus"]["claims_doc"] for f in faith_rows),
        },
        "faith_unsupported_total": {
            "sonnet": sum(f["sonnet"]["unsupported"] for f in faith_rows),
            "opus": sum(f["opus"]["unsupported"] for f in faith_rows),
        },
        "cost_usd": ev.METER.cost(),
    }
    args.cross_out.write_text(
        json.dumps(
            {"summary": summary, "rows": out_rows, "faith_rows": faith_rows},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--n", type=int, default=120)
    parser.add_argument("--out", type=Path, default=Path("eval/rag/runs/judge_calibration.json"))
    parser.add_argument("--cross", action="store_true", help="Opus 두 번째 판정자와 교차 검정")
    parser.add_argument("--max-usd", type=float, default=1.0)
    parser.add_argument("--cross-out", type=Path, default=Path("eval/rag/runs/judge_cross.json"))
    args = parser.parse_args()
    if args.cross:
        cross_main(args)
        return
    if args.source is None:
        parser.error("--source 가 필요합니다")
    ev.judge_budget_usd = args.max_usd
    public.verify_lock(args.source)
    with (args.source / "allganize" / "rag_evaluation_result.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    systems = [c[: -len("_ox")] for c in rows[0] if c.endswith("_ox")]
    pool: dict[str, list[dict]] = {"O": [], "X": []}
    for i, r in enumerate(rows):
        for system in systems:
            label = r[f"{system}_ox"]
            if label in pool and r[f"{system}_answer"].strip():
                pool[label].append(
                    {
                        "qid": f"q{i:03d}",
                        "system": system,
                        "question": r["question"],
                        "gold": r["target_answer"],
                        "answer": r[f"{system}_answer"],
                        "published": label,
                    }
                )
    rng = random.Random(SEED)
    sample = rng.sample(pool["O"], args.n // 2) + rng.sample(pool["X"], args.n // 2)
    results = []
    for item in sample:
        verdict = ev.judge_correct(item["question"], item["gold"], item["answer"])
        results.append({**item, "judge": "O" if verdict["correct"] else "X", **verdict})
    agree = sum(1 for r in results if r["judge"] == r["published"])
    summary = {
        "n": len(results),
        "agreement": round(agree / len(results), 4),
        "published_O_judged_X": sum(
            1 for r in results if r["published"] == "O" and r["judge"] == "X"
        ),
        "published_X_judged_O": sum(
            1 for r in results if r["published"] == "X" and r["judge"] == "O"
        ),
        "cost_usd": ev.METER.cost(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"summary": summary, "rows": results}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
