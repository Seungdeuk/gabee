"""글자 층이 거의 없는 쪽만 서비스의 Claude 읽기(doc_ai.read_pdf)로 읽어 저장소 밖 캐시에 쌓는다.

원본 데이터는 고치지 않는다. 쪽마다 바로 저장하므로 꺼져도 다시 실행하면 이어서 읽는다.

    PYTHONPATH=.:eval/rag python eval/rag/ocr_low_pages.py --source <rag_eval_data> --cache <ocr_cache.jsonl>
"""

import argparse
import io
import json
import tarfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pypdfium2

from app.shared.config import settings
from app.shared.llm import doc_ai

LOW_CHARS = 80  # 공백을 뺀 글자 수가 이보다 적으면 글자 층이 없는 쪽으로 본다


def low_pages(source: Path) -> list[tuple[str, int, bytes]]:
    out = []
    for path in sorted((source / "datalama").glob("*.tar")):
        with tarfile.open(path) as tar:
            names = {m.name for m in tar.getmembers()}
            for name in sorted(n for n in names if n.endswith(".json")):
                meta = json.loads(tar.extractfile(name).read())
                pdf_name = name[:-5] + ".pdf"
                if pdf_name not in names:
                    continue
                data = tar.extractfile(pdf_name).read()
                pdf = pypdfium2.PdfDocument(io.BytesIO(data))
                text = "".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
                pdf.close()
                if len("".join(text.split())) < LOW_CHARS:
                    out.append((meta["file_name"], int(meta["page_number"]), data))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=3)
    args = parser.parse_args()
    done: set[tuple[str, int]] = set()
    if args.cache.exists():
        for line in args.cache.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            done.add((row["file"], row["page"]))
    pages = [p for p in low_pages(args.source) if (p[0], p[1]) not in done]
    print(f"model {settings.ingest_ocr_model}, 끝남 {len(done)}, 남음 {len(pages)}", flush=True)
    lock = threading.Lock()
    counts = {"ok": 0, "fail": 0}

    def read(item: tuple[str, int, bytes]) -> None:
        file_name, page, data = item
        try:
            out = doc_ai.read_pdf(data)
            row = {"file": file_name, "page": page, "text": out.text, "cut": bool(out.truncated)}
        except Exception as exc:  # 실패한 쪽은 저장하지 않아 다음 실행 때 다시 읽는다
            with lock:
                counts["fail"] += 1
            print(f"실패 {page} {type(exc).__name__}", flush=True)
            return
        with lock:
            counts["ok"] += 1
            with args.cache.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + chr(10))
            if counts["ok"] % 20 == 0:
                print(f"읽음 {counts['ok']}/{len(pages)}", flush=True)

    with ThreadPoolExecutor(args.threads) as pool:
        list(pool.map(read, pages))
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
