"""공개 RAG 평가 데이터를 저장소 밖으로 받고 파일별 해시를 잠근다. 받은 뒤에는 파일을 고치지 않는다.

    python eval/rag/fetch_public_data.py --out <폴더>

- allganize/RAG-Evaluation-Dataset-KO (MIT): 질문·정답 CSV
- datalama/RAG-Evaluation-Dataset-KO (MIT): 같은 데이터에 PDF 를 묶은 재구성본

고정한 리비전만 받으므로 다시 받아도 같은 파일이다. tar 안의 파일은 실행하지 않고 평가 때 글자로만 읽는다."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

SOURCES = {
    "allganize": (
        "allganize/RAG-Evaluation-Dataset-KO",
        "35db50ff8739d78b11ee68b6f4ef04a95862a504",
    ),
    "datalama": ("datalama/RAG-Evaluation-Dataset-KO", "10eebed0e834794d8742fcc902678a9873db2f81"),
}


def _json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as res:
        return json.load(res)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    lock: dict[str, str] = {}
    for name, (repo, rev) in SOURCES.items():
        meta = _json(f"https://huggingface.co/api/datasets/{repo}/revision/{rev}")
        files = [
            s["rfilename"]
            for s in meta["siblings"]
            if s["rfilename"].endswith((".csv", ".tar", ".md", ".json", ".jsonl", ".parquet"))
        ]
        for rel in files:
            target = args.out / name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                url = f"https://huggingface.co/datasets/{repo}/resolve/{rev}/{rel}"
                urllib.request.urlretrieve(url, target)
            lock[f"{name}/{rel}"] = _sha(target)
        print(name, len(files), "files")
    (args.out / "data.lock.json").write_text(
        json.dumps({"sources": SOURCES, "sha256": lock}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    total = sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())
    print("total MB", round(total / 1e6, 1))


if __name__ == "__main__":
    main()
