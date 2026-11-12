"""문체별 평가셋(v4 등)을 평가한다(서비스 가명화 경로 ``detect_with_ner`` 또는 규칙 단독, 외부 호출 없음).

evaluate_v3.py(저장소 밖 gabee-ner-evalset-v3)의 full/partial/none·과마스킹 집계와 ml/ner/export/bench_onnx.py 의
100자 기준 지연 측정을 합친 것. v4 뿐 아니라 같은 스키마(``text``/``spans``/``known_names``/``category``)의 어떤
평가셋에도 쓸 수 있다.

사용: ``python eval_style_set.py <evalset.jsonl> <모델 폴더 또는 off> <결과.json>``
"""

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app.shared.privacy import ner  # noqa: E402
from app.shared.privacy.detectors import detect  # noqa: E402
from app.shared.privacy.types import Kind, Span  # noqa: E402

KIND = {"PERSON": Kind.PERSON, "ADDRESS": Kind.ADDRESS}


def score_rows(
    rows: list[dict], predict: Callable[[str, tuple[str, ...]], list[Span]]
) -> dict[str, Any]:
    """정답 구간마다 같은 종류의 예측이 글자를 덮은 정도로 full(전부)/partial(일부)/none(누출)을 센다.

    비인명 문장(정답 구간 없음)은 어떤 구간이든 잡히면 과마스킹(``flagged``)으로 센다.
    """
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "spans": 0,
            "full": 0,
            "partial": 0,
            "none": 0,
            "sentences": 0,
            "flagged": 0,
            "miss_examples": [],
        }
    )
    for r in rows:
        text = r["text"]
        spans = predict(text, tuple(r.get("known_names", ())))
        st = stats[r["category"]]
        st["sentences"] += 1
        if not r["spans"]:
            st["flagged"] += int(bool(spans))
            if spans and len(st["miss_examples"]) < 6:
                st["miss_examples"].append(
                    ["과마스킹", text, [text[s.start : s.end] for s in spans]]
                )
            continue
        for g in r["spans"]:
            st["spans"] += 1
            cov: set[int] = set()
            for s in spans:
                if s.kind is KIND[g["kind"]]:
                    cov.update(range(max(s.start, g["start"]), min(s.end, g["end"])))
            n = g["end"] - g["start"]
            key = "full" if len(cov) >= n else ("partial" if cov else "none")
            st[key] += 1
            if key != "full" and len(st["miss_examples"]) < 6:
                st["miss_examples"].append([key, text, text[g["start"] : g["end"]]])
    categories = dict(stats)
    person_total = {
        k: sum(v[k] for c, v in categories.items() if c not in ("주소", "비인명"))
        for k in ("spans", "full", "partial", "none")
    }
    return {"categories": categories, "person_total": person_total}


def _make_texts(pool: list[str], length: int, n: int) -> list[str]:
    """pool 문장을 이어 붙여 정확히 length 자인 문장 n 개를 만든다(bench_onnx.py 와 같은 방식)."""
    out = []
    for i in range(n):
        s, j = "", i
        while len(s) < length:
            s += pool[j % len(pool)] + " "
            j += 7
        out.append(s[:length])
    return out


def measure_latency(
    rows: list[dict], predict: Callable[[str], Any], *, char_len: int = 100, n: int = 105
) -> dict[str, Any]:
    """100자(기본) 문장 ``n``개에 대한 처리시간 중앙값·P95(ms). 처음 5개는 워밍업으로 버린다."""
    pool = [r["text"] for r in rows] or ["x"]
    texts = _make_texts(pool, char_len, n)
    samples: list[float] = []
    for i, t in enumerate(texts):
        t0 = time.perf_counter()
        predict(t)
        if i >= 5:
            samples.append(1000 * (time.perf_counter() - t0))
    samples.sort()
    return {
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(samples[min(len(samples) - 1, int(0.95 * len(samples)))], 3),
        "n": len(samples),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("evalset")
    ap.add_argument("model_dir_or_off")
    ap.add_argument("out")
    a = ap.parse_args(argv)

    import os

    ner.reset()
    if a.model_dir_or_off == "off":
        os.environ["PRIVACY_NER_MODE"] = "off"
    else:
        os.environ["PRIVACY_NER_MODE"] = "required"
        os.environ["PRIVACY_NER_MODEL_DIR"] = a.model_dir_or_off
        os.environ["PRIVACY_NER_THREADS"] = "2"

    status = ner.ner_status()
    if a.model_dir_or_off != "off" and not status["active"]:
        raise SystemExit(
            f"NER 엔진을 쓸 수 없다(모델 폴더 확인 필요): {a.model_dir_or_off}"
        )

    if a.model_dir_or_off == "off":
        predict2 = lambda text, known: detect(text, known)  # noqa: E731
    else:
        predict2 = lambda text, known: ner.detect_with_ner(text, known)  # noqa: E731
    predict1 = lambda text: predict2(text, ())  # noqa: E731

    rows = [json.loads(line) for line in Path(a.evalset).read_text(encoding="utf-8").splitlines() if line.strip()]
    out = {
        "mode": a.model_dir_or_off,
        "ner_status": status,
        **score_rows(rows, predict2),
        "latency_100chars": measure_latency(rows, predict1),
    }
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out["person_total"], ensure_ascii=False))


if __name__ == "__main__":
    main()
