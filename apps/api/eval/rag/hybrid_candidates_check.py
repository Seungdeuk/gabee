"""검색 실험(API 비용 0): 운영에 넣을 방식(임베딩 상위 N 개 후보 안에서만 TF-IDF 를 계산해 RRF 로 섞기)이
전체 조각 대상 섞기와 비슷한 효과를 내는지 후보 수별로 잰다. 색인 DB 는 읽기 전용으로 연다.

    PYTHONPATH=. python eval/rag/hybrid_candidates_check.py --index <public_ocr.db> --source <rag_eval_data>
    PYTHONPATH=. python eval/rag/hybrid_candidates_check.py --index <family_v2.db> --questions <questions.json>

- 임베딩만: 전체 조각을 임베딩 점수로 정렬(지금 서비스).
- 전체 섞기: hybrid_experiment.py 의 hybrid_tfidf23_w1 (전체 조각 idf, 전체 순위).
- 후보 N: 임베딩 상위 N 조각만 가져와 후보 묶음 기준 idf 로 TF-IDF 를 계산, 후보 안 순위로 RRF(k=60).
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import hybrid_experiment as hx
import retrieval_eval as public

RRF_K = 60


def fuse(es: list[float], texts: list[str], question: str, n: int, weight: float) -> list[int]:
    """임베딩 상위 n 개 후보를 TF-IDF 와 섞은 순서(조각 번호)."""
    cand = sorted(range(len(es)), key=lambda i: -es[i])[:n]
    tf = hx.TfIdf([hx.tokens23(texts[i]) for i in cand])
    ts = tf.scores(hx.tokens23(question))
    t_rank = {i: r for r, i in enumerate(sorted(range(len(cand)), key=lambda j: -ts[j]), 1)}
    return [
        cand[j]
        for j in sorted(
            range(len(cand)), key=lambda j: -(1 / (RRF_K + (j + 1)) + weight / (RRF_K + t_rank[j]))
        )
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--split", default="dev")
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--sizes", default="50,100,200")
    parser.add_argument("--weights", default="1.0")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    from app.features.ai_assistant.knowledge.embedding import get_embedder

    con = sqlite3.connect(f"file:{args.index}?mode=ro", uri=True)
    rows = con.execute(
        "select c.id, c.text, c.page_label, c.embedding, i.title, i.id from knowledge_chunks c "
        "join knowledge_items i on i.id = c.item_id"
    ).fetchall()
    texts = [r[1] for r in rows]
    pages = [r[2] for r in rows]
    titles = [public._stem(r[4]) for r in rows]
    item_ids = [r[5] for r in rows]
    vecs = [json.loads(r[3]) if isinstance(r[3], str) else r[3] for r in rows]
    if args.questions:
        qs = [
            q
            for q in json.loads(args.questions.read_text("utf-8"))["questions"]
            if q["split"] == args.split and q["kind"] == "answerable" and q.get("item_id")
        ]
        titles = list(item_ids)
        for q in qs:
            q["file"], q["page"] = q["item_id"], None
    else:
        qs = public.split_questions(public.load_questions(args.source))[args.split]
        known = public.load_pages_names(args.source)
        qs = [q for q in qs if q["file"] in known]
    sizes = [int(s) for s in args.sizes.split(",")]
    weights = [float(w) for w in args.weights.split(",")]
    emb = get_embedder()
    names = ["embedding", "full_hybrid"] + [f"cand{n}_w{w:g}" for n in sizes for w in weights]
    hits = {name: {} for name in names}
    ms = {name: [] for name in names}
    tf_full = hx.TfIdf([hx.tokens23(t) for t in texts])

    def docs_of(order: list[int]) -> list[tuple[str, str]]:
        seen, out = set(), []
        for i in order:
            if titles[i] not in seen:
                seen.add(titles[i])
                out.append((titles[i], pages[i]))
        return out

    for q in qs:
        qv = emb.embed_query(q["question"])
        es = [sum(a * b for a, b in zip(qv, v, strict=False)) for v in vecs]
        e_order = sorted(range(len(rows)), key=lambda i: -es[i])
        orders = {"embedding": e_order}
        ts = tf_full.scores(hx.tokens23(q["question"]))
        t_rank = {i: r for r, i in enumerate(sorted(range(len(rows)), key=lambda i: -ts[i]), 1)}
        e_rank = {i: r for r, i in enumerate(e_order, 1)}
        orders["full_hybrid"] = sorted(
            range(len(rows)), key=lambda i: -(1 / (RRF_K + e_rank[i]) + 1 / (RRF_K + t_rank[i]))
        )
        for n in sizes:
            for w in weights:
                t0 = time.perf_counter()
                orders[f"cand{n}_w{w:g}"] = fuse(es, texts, q["question"], n, w)
                ms[f"cand{n}_w{w:g}"].append((time.perf_counter() - t0) * 1000)
        gold = q["file"] if args.questions else public._stem(q["file"])
        gold_page = f"p.{q['page']}" if q["page"] else None
        for name, order in orders.items():
            docs = docs_of(order)
            for k in (1, 3, 5):
                top = docs[:k]
                h = hits[name]
                h[f"file@{k}"] = h.get(f"file@{k}", 0) + any(t == gold for t, _ in top)
                h[f"page@{k}"] = h.get(f"page@{k}", 0) + any(
                    t == gold and (gold_page is None or p == gold_page) for t, p in top
                )
    n = len(qs)
    result = {name: {k: round(v / n * 100, 1) for k, v in h.items()} for name, h in hits.items()}
    for name, vals in ms.items():
        if vals:
            result[name]["tfidf_ms_mean"] = round(sum(vals) / len(vals), 1)
    result["n"] = n
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
