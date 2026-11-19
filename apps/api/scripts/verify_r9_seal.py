"""R9 봉인 평가셋 무결성 확인(읽기 전용): MANIFEST.sha256 과 파일 해시, 읽기 전용 속성, 행 수. 원문은 출력하지 않는다.

사용: python verify_r9_seal.py [--dir <sealed 폴더>]
"""

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=Path(r"C:\Users\403\Documents\gabee-ner-sealed-r9\sealed"))
    a = ap.parse_args()
    bad, rows = [], {}
    lines = (a.dir / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    listed = set()
    for ln in lines:
        h, n = ln.split(" *", 1)
        listed.add(n)
        p = a.dir / n
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
            bad.append(("hash_mismatch_or_missing", n))
        if os.access(p, os.W_OK) or (p.exists() and p.stat().st_mode & stat.S_IWRITE):
            bad.append(("not_read_only", n))
        if n.endswith(".jsonl"):
            rows[n] = sum(1 for l in p.read_text(encoding="utf-8").splitlines() if l.strip())
    extra = sorted(p.name for p in a.dir.iterdir() if p.name not in listed and p.name != "MANIFEST.sha256")
    if extra:
        bad.append(("unlisted_files", ",".join(extra)))
    m = json.loads((a.dir / "R9_v1.2_SEAL_MANIFEST.json").read_text(encoding="utf-8"))
    for d in m["datasets"]:
        if rows.get(d["name"]) != d["rows"]:
            bad.append(("row_count_mismatch", d["name"]))
    print(json.dumps({"status": m["status"], "files_checked": len(lines), "jsonl_rows": rows, "problems": bad}, ensure_ascii=False))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
