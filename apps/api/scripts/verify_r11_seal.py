"""R11 봉인 평가셋 무결성 확인(읽기 전용): MANIFEST.sha256 과 파일 해시, 읽기 전용 속성, 행 수. 원문은 출력하지 않는다.

사용: python verify_r11_seal.py --dir <sealed 폴더>
"""

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path


def check(d):
    bad, rows, listed = [], {}, set()
    for ln in (d / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        h, n = ln.split(" *", 1)
        listed.add(n)
        p = d / n
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
            bad.append(("hash_mismatch_or_missing", n))
        if p.exists() and (os.access(p, os.W_OK) or p.stat().st_mode & stat.S_IWRITE):
            bad.append(("not_read_only", n))
        if n.endswith(".jsonl") and p.exists():
            rows[n] = sum(1 for x in p.read_text(encoding="utf-8").splitlines() if x.strip())
    extra = sorted(p.name for p in d.iterdir() if p.name not in listed and p.name != "MANIFEST.sha256")
    if extra:
        bad.append(("unlisted_files", ",".join(extra)))
    m = json.loads((d / "R11_OPS_SEAL_MANIFEST.json").read_text(encoding="utf-8"))
    for x in m["datasets"]:
        if rows.get(x["name"]) != x["rows"]:
            bad.append(("row_count_mismatch", x["name"]))
    return {"status": m["status"], "files_checked": len(listed), "jsonl_rows": rows, "problems": bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, required=True)
    res = check(ap.parse_args().dir)
    print(json.dumps(res, ensure_ascii=False))
    return 1 if res["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
