"""헤드리스(Claude Code) 판정이 API 판정과 같은지 확인한다. 같은 입력을 다시 판정해 저장된 API 판정과 견준다.

API 비용은 들지 않는다(구독 사용량). 가비의 답은 다시 만들지 않는다.

    GABEE_JUDGE_BACKEND=cli PYTHONPATH=. python eval/rag/calibrate_cli_judge.py
"""

import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import answer_eval as ev

SEED = 20261114
RUNS = Path("eval/rag/runs")


def _agree(pairs: list[tuple[object, object]]) -> dict:
    same = sum(1 for a, b in pairs if a == b)
    return {"n": len(pairs), "agree": same, "rate": round(same / len(pairs), 4) if pairs else None}


def main() -> None:
    assert ev.JUDGE_BACKEND == "cli", "GABEE_JUDGE_BACKEND=cli 로 실행하세요"
    rng = random.Random(SEED)
    cal = json.loads((RUNS / "judge_calibration.json").read_text("utf-8"))["rows"]
    rows, _ = ev.read_partial(RUNS / "answer_dev_untuned.partial.jsonl")
    ok = [r for r in rows.values() if r.get("ai") and r.get("v") == ev.SCORING_VERSION]
    no_ans = rng.sample([r for r in ok if r["kind"] == "no_answer"], 20)
    faith = rng.sample(
        [r for r in ok if r["kind"] == "answerable" and 0 < len(r.get("context", "")) <= 8000], 20
    )

    def correct(item: dict) -> dict:
        v = ev.judge_correct(item["question"], item["gold"], item["answer"])
        return {
            "qid": item["qid"],
            "api": item["judge"],
            "cli": "O" if v["correct"] else "X",
            "published": item["published"],
        }

    def abstain(r: dict) -> dict:
        v = ev.judge_abstain(r["question"], r["answer"])
        return {
            "qid": r["qid"],
            "api": r["abstain_status"],
            "cli": ev.abstain_status(
                bool(v.get("abstained")), bool(v.get("gave_other_value")), r.get("tools", [])
            ),
        }

    def faith_one(r: dict) -> dict:
        v = ev.judge_faith(r["context"], r["answer"])
        doc = [c for c in v.get("claims", []) if isinstance(c, dict) and c.get("kind") != "meta"]
        return {
            "qid": r["qid"],
            "api_unsupported": len(r.get("unsupported", [])),
            "cli_unsupported": sum(1 for c in doc if not c.get("supported")),
        }

    with ThreadPoolExecutor(4) as pool:
        c_rows = list(pool.map(correct, cal))
        a_rows = list(pool.map(abstain, no_ans))
        f_rows = list(pool.map(faith_one, faith))
    summary = {
        "correct_vs_api": _agree([(r["api"], r["cli"]) for r in c_rows]),
        "correct_vs_published": _agree([(r["published"], r["cli"]) for r in c_rows]),
        "api_vs_published": _agree([(r["published"], r["api"]) for r in c_rows]),
        "abstain_status_vs_api": _agree([(r["api"], r["cli"]) for r in a_rows]),
        "faith_has_unsupported_vs_api": _agree(
            [(r["api_unsupported"] > 0, r["cli_unsupported"] > 0) for r in f_rows]
        ),
        "faith_unsupported_total": {
            "api": sum(r["api_unsupported"] for r in f_rows),
            "cli": sum(r["cli_unsupported"] for r in f_rows),
        },
        "cli": ev.CLI_STATS,
        "api_cost_usd": ev.METER.cost(),
        "note": "API 판정은 저장된 값(같은 Sonnet 5.5, 같은 판정문). 차이는 경로·무작위성에서 온다. total_cost_usd 는 구독 사용분의 환산값이라 청구액이 아니다.",
    }
    out = RUNS / "judge_cli_vs_api.json"
    out.write_text(
        json.dumps(
            {"summary": summary, "correct": c_rows, "abstain": a_rows, "faith": f_rows},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
