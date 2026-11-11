"""검색 실험(API 비용 0): 지금 임베딩 검색과, 낱말 일치(BM25) 를 섞은 검색을 같은 색인·같은 문항으로 견준다.

서비스 코드는 바꾸지 않는다. 색인 DB 는 읽기만 한다.

    PYTHONPATH=. python eval/rag/hybrid_experiment.py --index <public_ocr.db> --source <rag_eval_data>

- 낱말: 한글은 글자 두 개씩(bigram), 영문·숫자는 낱말 단위. 조사가 붙어도 걸리게 하려는 단순 방식이다.
- 섞기: 순위 합치기(RRF, k=60). 가중치는 임베딩 1, BM25 w(인자).
- 서비스처럼 문서마다 가장 높은 조각 하나를 대표로 두고 상위 문서의 대표 조각 쪽을 본다(대표 조각 기준).
"""

import argparse
import json
import math
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import retrieval_eval as public

TOKEN = re.compile(r"[가-힣]+|[A-Za-z]+|\d+")


def tokens(text: str) -> list[str]:
    out = []
    for w in TOKEN.findall(text.lower()):
        if re.match(r"[가-힣]", w):
            out += [w[i : i + 2] for i in range(max(1, len(w) - 1))]
        else:
            out.append(w)
    return out


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / len(self.len)
        df = Counter(t for d in self.tf for t in d)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, q: list[str]) -> list[float]:
        out = []
        for tf, ln in zip(self.tf, self.len, strict=True):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += (
                        self.idf[t]
                        * f
                        * (self.k1 + 1)
                        / (f + self.k1 * (1 - self.b + self.b * ln / self.avg))
                    )
            out.append(s)
        return out


class TfIdf:
    """글자 n-gram TF-IDF 코사인(분류기와 같은 계열). sublinear tf, l2 정규화."""

    def __init__(self, docs: list[list[str]]):
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.vecs = [self._vec(Counter(d)) for d in docs]

    def _vec(self, tf: Counter) -> dict:
        v = {t: (1 + math.log(c)) * self.idf.get(t, 0.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    def scores(self, q: list[str]) -> list[float]:
        qv = self._vec(Counter(q))
        return [sum(w * d.get(t, 0.0) for t, w in qv.items()) for d in self.vecs]


def tokens23(text: str) -> list[str]:
    """한글은 글자 2·3개 묶음, 영문·숫자는 낱말."""
    out = []
    for w in TOKEN.findall(text.lower()):
        if re.match(r"[가-힣]", w):
            out += [w[i : i + 2] for i in range(max(1, len(w) - 1))]
            out += [w[i : i + 3] for i in range(len(w) - 2)]
        else:
            out.append(w)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--split", default="dev")
    parser.add_argument("--questions", type=Path, help="가족 셋 질문 파일(item_id 정답)")
    parser.add_argument("--out", type=Path, default=Path("eval/rag/runs/hybrid_experiment.json"))
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
    bm = BM25([tokens(t) for t in texts])
    tf2 = TfIdf([tokens(t) for t in texts])
    tf23 = TfIdf([tokens23(t) for t in texts])
    emb = get_embedder()
    if args.questions:  # 가족 셋: 정답은 item_id, 쪽 없음
        qs = [
            q
            for q in json.loads(args.questions.read_text("utf-8"))["questions"]
            if q["split"] == args.split and q["kind"] == "answerable" and q.get("item_id")
        ]
        for i, iid in enumerate(item_ids):
            titles[i] = iid
        for q in qs:
            q["file"], q["page"] = q["item_id"], None
    else:
        qs = public.split_questions(public.load_questions(args.source))[args.split]
        known = public.load_pages_names(args.source)
        qs = [q for q in qs if q["file"] in known]

    def rank_docs(order: list[int]) -> list[tuple[str, str]]:
        seen, out = set(), []
        for i in order:
            if titles[i] not in seen:
                seen.add(titles[i])
                out.append((titles[i], pages[i]))
        return out

    configs = {
        "tfidf2_only": "tf2",
        "tfidf23_only": "tf23",
        "hybrid_tfidf2_w1": ("tf2", 1.0),
        "hybrid_tfidf23_w1": ("tf23", 1.0),
        "embedding": None,
        "hybrid_w0.5": 0.5,
        "hybrid_w1": 1.0,
        "hybrid_w2": 2.0,
        "bm25_only": "bm25",
    }
    hits = {name: defaultdict(int) for name in configs}
    for q in qs:
        qv = emb.embed_query(q["question"])
        es = [sum(a * b for a, b in zip(qv, v, strict=False)) for v in vecs]
        bs = bm.scores(tokens(q["question"]))
        e_rank = {i: r for r, i in enumerate(sorted(range(len(rows)), key=lambda i: -es[i]), 1)}
        b_rank = {i: r for r, i in enumerate(sorted(range(len(rows)), key=lambda i: -bs[i]), 1)}
        ts = {
            "tf2": tf2.scores(tokens(q["question"])),
            "tf23": tf23.scores(tokens23(q["question"])),
        }
        t_rank = {
            k: {i: r for r, i in enumerate(sorted(range(len(rows)), key=lambda i: -v[i]), 1)}
            for k, v in ts.items()
        }
        gold_file = q["file"] if args.questions else public._stem(q["file"])
        gold_page = f"p.{q['page']}" if q["page"] else None
        for name, w in configs.items():
            if isinstance(w, tuple):
                tr = t_rank[w[0]]
                order = sorted(
                    range(len(rows)), key=lambda i: -(1 / (60 + e_rank[i]) + w[1] / (60 + tr[i]))
                )
            elif w in ("tf2", "tf23"):
                order = sorted(range(len(rows)), key=lambda i: -ts[w][i])
            elif w is None:
                order = sorted(range(len(rows)), key=lambda i: -es[i])
            elif w == "bm25":
                order = sorted(range(len(rows)), key=lambda i: -bs[i])
            else:
                order = sorted(
                    range(len(rows)), key=lambda i: -(1 / (60 + e_rank[i]) + w / (60 + b_rank[i]))
                )
            docs = rank_docs(order)
            for k in (1, 3, 5):
                top = docs[:k]
                hits[name][f"file@{k}"] += any(t == gold_file for t, _ in top)
                hits[name][f"page@{k}"] += any(
                    t == gold_file and (gold_page is None or p == gold_page) for t, p in top
                )
    n = len(qs)
    result = {name: {k: round(v / n, 4) for k, v in h.items()} for name, h in hits.items()}
    result["n"] = n
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
