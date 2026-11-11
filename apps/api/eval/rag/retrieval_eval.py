"""RAG 검색 평가: 공개 데이터(allganize 한국어 실제 PDF)로 서비스 검색 코드를 그대로 재서 Hit@k·MRR 을 낸다.

임시 SQLite 만 쓰고, LLM 을 부르지 않는다. 평가 데이터는 읽기만 한다(data.lock.json 해시가 다르면 멈춘다).

    PYTHONPATH=. python eval/rag/retrieval_eval.py --split dev --name baseline --source <rag_eval_data> --out eval/rag/runs

- 나누기: 질문을 영역별로 시드 고정 70% dev / 30% test. 루프는 dev 만 본다. test 는 --split test 로 목표 달성 때만 실행한다.
- 정답: 질문의 target_file_name(파일), target_page_no(쪽). 파일 맞춤과 쪽 맞춤을 따로 잰다.
- 본문: PDF 글자 층. 운영의 Claude OCR 결과와 다르다(표·그림 근거는 불리하다). 묶음별로 보고한다.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import random
import re
import shutil
import sys
import tarfile
import tempfile
import time
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(10**8)
_tmp = tempfile.mkdtemp(prefix="gabee-rag-eval-")
_reuse = sys.argv[sys.argv.index("--reuse-index") + 1] if "--reuse-index" in sys.argv else None
# 실제 DB 는 건드리지 않는다. --reuse-index 는 이미 만든 평가 색인 파일을 읽기만 한다
os.environ["DATABASE_URL"] = f"sqlite:///{_reuse}" if _reuse else f"sqlite:///{_tmp}/eval.db"

SEED = 20261109
KS = (1, 3, 5, 10)


def verify_lock(source: Path) -> None:
    lock = json.loads((source / "data.lock.json").read_text(encoding="utf-8"))["sha256"]
    for rel, want in lock.items():
        digest = hashlib.sha256((source / rel).read_bytes()).hexdigest()
        if digest != want:
            raise SystemExit(f"평가 데이터가 바뀌었어요: {rel}")


def load_questions(source: Path) -> list[dict]:
    with (source / "allganize" / "rag_evaluation_result.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for i, r in enumerate(rows):
        out.append(
            {
                "qid": f"q{i:03d}",
                "domain": r["domain"],
                "question": r["question"],
                "answer": r["target_answer"],
                "file": r["target_file_name"],
                "page": str(r["target_page_no"]).strip(),
                "context_type": r["context_type"],
            }
        )
    return out


def split_questions(questions: list[dict]) -> dict[str, list[dict]]:
    """영역별로 섞어 70/30 으로 나눈다. 시드가 고정이라 다시 돌려도 같다."""
    rng = random.Random(SEED)
    by_domain = defaultdict(list)
    for q in questions:
        by_domain[q["domain"]].append(q)
    split = {"dev": [], "test": []}
    for domain in sorted(by_domain):
        items = by_domain[domain][:]
        rng.shuffle(items)
        cut = round(len(items) * 0.7)
        split["dev"] += items[:cut]
        split["test"] += items[cut:]
    return split


def load_pages(source: Path) -> dict[str, dict[int, str]]:
    """{파일 이름: {쪽 번호: 글자 층}}. tar 의 PDF 는 글자로만 읽는다."""
    import pypdfium2

    pages: dict[str, dict[int, str]] = defaultdict(dict)
    for path in sorted((source / "datalama").glob("*.tar")):
        with tarfile.open(path) as tar:
            names = {m.name for m in tar.getmembers()}
            for name in sorted(n for n in names if n.endswith(".json")):
                meta = json.loads(tar.extractfile(name).read())
                pdf_name = name[:-5] + ".pdf"
                if pdf_name not in names:
                    continue
                pdf = pypdfium2.PdfDocument(io.BytesIO(tar.extractfile(pdf_name).read()))
                text = "\n".join(
                    pdf[i].get_textpage().get_text_range() for i in range(len(pdf))
                ).replace("\r", "")
                pages[meta["file_name"]][int(meta["page_number"])] = text
    return pages


def load_pages_names(source: Path) -> set[str]:
    """묶음에 들어 있는 문서 파일 이름."""
    names: set[str] = set()
    for path in sorted((source / "datalama").glob("*.tar")):
        with tarfile.open(path) as tar:
            first = next(m.name for m in tar.getmembers() if m.name.endswith(".json"))
            names.add(json.loads(tar.extractfile(first).read())["file_name"])
    return names


def build_index(pages: dict[str, dict[int, str]]) -> tuple[str, int]:
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from app.features.ai_assistant.knowledge import service
    from app.features.ai_assistant.knowledge.models import KnowledgeChunk
    from app.features.family_group.models import User
    from app.main import app
    from app.shared.db import SessionLocal, init_db
    from tests.helpers import signup

    init_db()
    client = TestClient(app)
    headers = signup(client, "평가", "parent")
    group = client.post("/family-group/groups", json={"name": "평가"}, headers=headers).json()
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.name == "평가"))
        for i, (file_name, numbered) in enumerate(sorted(pages.items())):
            body = "\n".join(f"[p.{n}]\n{numbered[n]}" for n in sorted(numbered))
            title = Path(file_name).stem[:190]
            md = f"# {title}\n분류: 문서\n{body}"
            service.ingest(db, group["id"], uid, kind_label="문서", title=title, body_md=md)
            print(f"색인 {i + 1}/{len(pages)}", flush=True)
        chunks = db.scalar(select(func.count()).select_from(KnowledgeChunk))
    return group["id"], int(chunks)


def existing_index() -> tuple[str, int]:
    from sqlalchemy import func, select

    from app.features.ai_assistant.knowledge.models import KnowledgeChunk, KnowledgeItem
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        return (
            db.scalars(select(KnowledgeItem.group_id).limit(1)).first(),
            int(db.scalar(select(func.count()).select_from(KnowledgeChunk))),
        )


def _stem(name: str) -> str:
    # 제목에는 확장자가 없다. Path.stem 은 '14.cancer_info' 를 '14' 로 잘라 정답을 놓치게 만들었다(2026-11-09 수정).
    return re.sub(r"\s+", "", re.sub(r"\.pdf$", "", name, flags=re.I))[:60]


def run(questions: list[dict], group_id: str) -> list[dict]:
    from app.features.ai_assistant.knowledge import repository as repo
    from app.features.ai_assistant.knowledge.embedding import get_embedder
    from app.shared.db import SessionLocal

    embedder = get_embedder()
    out = []
    with SessionLocal() as db:
        for q in questions:
            started = time.perf_counter()
            rows = repo.search_chunks(
                db,
                group_id,
                embedder.name,
                embedder.embed_query(q["question"]),
                None,
                None,
                None,
                True,
            )
            ms = (time.perf_counter() - started) * 1000
            ranked_files: list[str] = []
            page_rank = None
            for rank, (chunk, item, _score) in enumerate(rows, 1):
                stem = _stem(item.title)
                if stem not in ranked_files:
                    ranked_files.append(stem)
                if (
                    page_rank is None
                    and stem == _stem(q["file"])
                    and chunk.page_label == f"p.{q['page']}"
                ):
                    page_rank = rank
            gold = _stem(q["file"])
            file_rank = ranked_files.index(gold) + 1 if gold in ranked_files else None
            out.append({**q, "file_rank": file_rank, "page_rank": page_rank, "ms": round(ms, 1)})
    return out


def metrics(rows: list[dict], key: str) -> dict:
    n = len(rows) or 1
    res = {f"hit@{k}": round(sum(1 for r in rows if r[key] and r[key] <= k) / n, 4) for k in KS}
    res["mrr"] = round(sum(1 / r[key] for r in rows if r[key]) / n, 4)
    res["n"] = len(rows)
    return res


def report(rows: list[dict]) -> dict:
    groups = {"all": rows}
    for field in ("domain", "context_type"):
        for value in sorted({r[field] for r in rows}):
            groups[f"{field}={value}"] = [r for r in rows if r[field] == value]
    latencies = sorted(r["ms"] for r in rows)
    return {
        "file": {name: metrics(items, "file_rank") for name, items in groups.items()},
        "page": {name: metrics(items, "page_rank") for name, items in groups.items()},
        "latency_ms_p50": latencies[len(latencies) // 2] if latencies else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--name", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("eval/rag/runs"))
    parser.add_argument("--reuse-index", type=Path, help="이미 만든 평가 색인 DB")
    parser.add_argument("--ocr-cache", type=Path, help="글자 층이 없는 쪽을 Claude 로 읽은 캐시")
    parser.add_argument("--save-index", type=Path, help="만든 색인을 이 파일로 복사")
    args = parser.parse_args()
    verify_lock(args.source)
    split = split_questions(load_questions(args.source))
    pages = load_pages(args.source)
    if args.ocr_cache:
        for line in args.ocr_cache.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            pages[row["file"]][row["page"]] = row["text"]
    missing = sorted({q["file"] for q in split["dev"] + split["test"]} - set(pages))
    if args.reuse_index:
        group_id, chunks = existing_index()
    else:
        group_id, chunks = build_index(pages)
    if args.save_index:
        shutil.copyfile(f"{_tmp}/eval.db", args.save_index)
    # 정답 문서가 묶음에 없는 문항은 어떤 시스템도 맞힐 수 없어 뺀다(개수는 결과에 남긴다)
    rows = run([q for q in split[args.split] if q["file"] not in missing], group_id)
    result = {
        "name": args.name,
        "note": args.note,
        "split": args.split,
        "documents": len(pages),
        "pages": sum(len(v) for v in pages.values()),
        "chunks": chunks,
        "files_missing": missing,
        "metrics": report(rows),
        "misses": [
            {
                k: r[k]
                for k in (
                    "qid",
                    "domain",
                    "context_type",
                    "question",
                    "file",
                    "page",
                    "file_rank",
                    "page_rank",
                )
            }
            for r in rows
            if not (r["page_rank"] and r["page_rank"] <= 5)
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"retrieval_{args.split}_{args.name}.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("documents", "pages", "chunks")}, ensure_ascii=False))
    print(
        json.dumps(result["metrics"]["file"]["all"]), json.dumps(result["metrics"]["page"]["all"])
    )
    print("missing files", len(missing), file=sys.stderr)


if __name__ == "__main__":
    main()
