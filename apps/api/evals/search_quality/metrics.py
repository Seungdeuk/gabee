"""검색 지표. 모두 순수 함수(DB·모델 없음). 정의와 분모는 docs/features/agent-eval-search-quality.md 와 같다.

입력은 순위순 메시지 키 목록이다. 에이전트 검색은 한 번에 최대 `K` 건(기본 limit 10)만 돌려주므로 지표도 상위 K 로 계산한다.

- gold: 질문의 정답 근거. 정답으로 세는 것은 gold 뿐이다(`acceptable` 은 같은 주제의 맥락 글이라 정답도 오답도 아니다).
- Hit@K: 상위 K 에 gold 가 하나라도 있으면 1. 분모: gold 가 있는 사례 수.
- Recall@K: |상위 K ∩ gold| / |gold|. 분모: gold 가 있는 사례 수.
- Precision@K: |상위 K ∩ gold| / K (분모는 K 로 고정, 반환 개수가 K 보다 적어도 K 로 나눈다).
- Precision@returned: |상위 K ∩ gold| / 실제 반환 개수. 반환이 0 건이면 정의되지 않아 평균에서 빼고 건수(`undefined`)만 센다.
- MRR@K: 첫 gold 의 순위 역수(없으면 0). 분모: gold 가 있는 사례 수. 맥락 글(acceptable)은 순위에 쓰지 않는다.
- gold 가 없는 사례는 위 지표에 넣지 않고 no-answer 지표(빈 결과가 맞다)와 범위 위반(금지·범위 밖 글이 나왔는가)으로만 본다.
"""

K = 10


def case_metrics(retrieved: list[str], gold: list[str], acceptable: list[str], k: int = K) -> dict:
    """한 사례·한 검색어 묶음의 지표. `retrieved` 는 순위순 키(최대 k 개로 자른다)."""
    top = list(retrieved[:k])
    gold_set, ok_set = set(gold), set(acceptable)
    gold_hits = [x for x in top if x in gold_set]
    first = next((i for i, x in enumerate(top, 1) if x in gold_set), None)
    out = {
        "returned": len(top),
        "gold_hits": len(gold_hits),
        "context_hits": sum(1 for x in top if x in ok_set),
        "irrelevant": sum(1 for x in top if x not in gold_set and x not in ok_set),
        "first_gold_rank": first,
    }
    if gold:
        out |= {
            "hit": 1.0 if gold_hits else 0.0,
            "recall": len(gold_hits) / len(gold_set),
            "precision_at_k": len(gold_hits) / k,
            "precision_returned": (len(gold_hits) / len(top)) if top else None,
            "mrr": (1.0 / first) if first else 0.0,
        }
    return out


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def aggregate(rows: list[dict]) -> dict:
    """gold 가 있는 사례들의 평균. 각 행은 `case_metrics` 결과(gold 가 있는 것만 넘긴다)."""
    returned_rows = [r["precision_returned"] for r in rows if r["precision_returned"] is not None]
    return {
        "cases": len(rows),
        "hit": _mean([r["hit"] for r in rows]),
        "recall": _mean([r["recall"] for r in rows]),
        "precision_at_k": _mean([r["precision_at_k"] for r in rows]),
        "precision_returned": _mean(returned_rows),
        "precision_returned_undefined": len(rows) - len(returned_rows),
        "mrr": _mean([r["mrr"] for r in rows]),
    }


def no_answer(rows: list[dict]) -> dict:
    """gold 가 없는 사례들. 각 행: {"returned": 건수, "violations": 범위 위반 수}."""
    return {
        "cases": len(rows),
        "correct_empty": sum(1 for r in rows if r["returned"] == 0),
        "nonempty": sum(1 for r in rows if r["returned"] > 0),
        "violations": sum(r["violations"] for r in rows),
    }
