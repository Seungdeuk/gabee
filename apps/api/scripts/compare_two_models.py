"""두 모델을 같은 평가셋에서 정답 구간 단위로 대응(paired) 비교한다(R1/R2 비교용).

``eval_style_set.py``는 모델별 집계만 낸다. 여기서는 정답 구간마다 두 모델의 판정
(full/partial/none)을 나란히 매겨, 한쪽만 나빠진(또는 좋아진) 구체적 예시를 뽑는다.

사용: python compare_two_models.py <evalset.jsonl> <모델A 폴더> <모델B 폴더> [--out 결과.json]
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app.shared.config import settings  # noqa: E402
from app.shared.privacy import ner  # noqa: E402
from app.shared.privacy.types import Kind  # noqa: E402

KIND = {"PERSON": Kind.PERSON}


def load_model(model_dir: str) -> dict[str, Any]:
    ner.reset()
    settings.privacy_ner_mode = "required"
    settings.privacy_ner_model_dir = model_dir
    settings.privacy_ner_threads = 2
    status = ner.ner_status()
    if not status["active"]:
        raise SystemExit(f"NER 엔진을 쓸 수 없다: {model_dir}")
    return status


def judge(text: str, g: dict, known_names: tuple[str, ...]) -> tuple[str, list]:
    final = ner.detect_with_ner(text, known_names)
    cov: set[int] = set()
    all_spans = []
    for s in final:
        if s.kind is KIND[g["kind"]]:
            overlap = range(max(s.start, g["start"]), min(s.end, g["end"]))
            if overlap:
                cov.update(overlap)
        all_spans.append((s.kind.name, round(s.score, 3), text[s.start : s.end]))
    n = g["end"] - g["start"]
    status = "full" if len(cov) >= n else ("partial" if cov else "none")
    return status, all_spans


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("evalset")
    ap.add_argument("model_a")
    ap.add_argument("model_b")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    rows = [
        json.loads(line)
        for line in Path(a.evalset).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    load_model(a.model_a)
    a_judge = {}
    for r in rows:
        for gi, g in enumerate(r.get("spans", [])):
            if g["kind"] != "PERSON":
                continue
            status, spans = judge(r["text"], g, tuple(r.get("known_names", ())))
            a_judge[(r["id"], gi)] = (status, spans)

    load_model(a.model_b)
    b_judge = {}
    for r in rows:
        for gi, g in enumerate(r.get("spans", [])):
            if g["kind"] != "PERSON":
                continue
            status, spans = judge(r["text"], g, tuple(r.get("known_names", ())))
            b_judge[(r["id"], gi)] = (status, spans)

    rank = {"full": 2, "partial": 1, "none": 0}
    transitions: Counter = Counter()
    worsened: list[dict] = []
    improved: list[dict] = []
    by_id = {r["id"]: r for r in rows}
    for key in a_judge:
        sa, spans_a = a_judge[key]
        sb, spans_b = b_judge[key]
        transitions[(sa, sb)] += 1
        if rank[sb] < rank[sa]:
            rid, gi = key
            r = by_id[rid]
            g = r["spans"][gi]
            worsened.append(
                {
                    "id": rid,
                    "text": r["text"],
                    "gold": r["text"][g["start"] : g["end"]],
                    "A": sa,
                    "B": sb,
                    "A_spans": spans_a,
                    "B_spans": spans_b,
                }
            )
        elif rank[sb] > rank[sa]:
            rid, gi = key
            r = by_id[rid]
            g = r["spans"][gi]
            improved.append(
                {
                    "id": rid,
                    "text": r["text"],
                    "gold": r["text"][g["start"] : g["end"]],
                    "A": sa,
                    "B": sb,
                }
            )

    out = {
        "model_a": Path(a.model_a).name,
        "model_b": Path(a.model_b).name,
        "n_gold_spans": len(a_judge),
        "transition_matrix": {f"{k[0]}->{k[1]}": v for k, v in sorted(transitions.items())},
        "worsened_count": len(worsened),
        "improved_count": len(improved),
        "worsened_examples": worsened,
        "improved_examples": improved,
    }
    if a.out:
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {
                "n": out["n_gold_spans"],
                "worsened": out["worsened_count"],
                "improved": out["improved_count"],
                "transitions": out["transition_matrix"],
            },
            ensure_ascii=False,
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
