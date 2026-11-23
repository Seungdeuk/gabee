"""R11 독립 평가셋 수량 맞춤(예비분 제거). 사양 `NER_R11_EVALSET_SPEC.md` r11-1.0 §3, 절차 문서 8단계. 문장 원문은 출력하지 않는다.

제작 세션이 예비분(+10%)을 포함해 만든 변환 결과(JSONL)에서 **정확한 최종 수량(2,350문장)** 이 되도록 문장을 덜어낸다.
- 우선 제거: `--prefer-drop` 으로 준 id(검증 오류·겹침으로 지적된 문장; 쌍이면 쌍 전체). 그다음 SHA256('r11-ops-trim-1.0|' + key) 큰 순서로 제거(결정적 무작위, 모델 결과와 무관).
- 쌍 유형(D1P/D1)은 쌍(pair_id) 단위로 300쌍. 최종 수량에 모자라는 유형이 있으면 중단하고 부족 건수를 알린다(임의 보충 금지).
- 제거한 id 목록은 `--removed-out` 에 기록한다.
사용: python trim_r11_evalset.py --in converted.jsonl --out trimmed.jsonl --removed-out removed.json [--prefer-drop ids.json]
"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

PREFIX = "r11-ops-trim-1.0|"
FINAL = {"A1": 150, "A3": 100, "B1": 240, "B2": 80, "C1": 100, "C2": 200, "D3": 100, "D2": 100, "A3N": 60, "GENERIC": 40, "OTHER": 50, "NEWNAME": 310, "LONGNAME": 120, "ORGLOC_MIX": 100}
PAIRS_FINAL = 300
PAIR_TYPES = ("D1P", "D1")


def _h(key):
    return hashlib.sha256((PREFIX + str(key)).encode("utf-8")).hexdigest()


def trim(rows, final=None, pairs_final=PAIRS_FINAL, prefer_drop=()):
    """rows: 변환된 행 목록. 반환: (유지 행, 제거 id 목록, 오류 목록). 오류가 있으면 유지 행은 비어 있다."""
    final = FINAL if final is None else final
    prefer = set(prefer_drop)
    by = defaultdict(list)
    for r in rows:
        by[r.get("primary_stress_type")].append(r)
    errors = [f"허용 목록 밖 유형: {t}" for t in by if t not in final and t not in PAIR_TYPES]
    keep_ids, removed = set(), []
    for ty, n in final.items():
        pool = by.get(ty, [])
        if len(pool) < n:
            errors.append(f"{ty}: {len(pool)} < {n} (부족 {n - len(pool)})")
            continue
        # 남길 우선순위: prefer-drop 이 아닌 것 먼저, 그다음 해시 작은 순
        order = sorted(pool, key=lambda r: (r["id"] in prefer, _h(r["id"])))
        keep_ids |= {r["id"] for r in order[:n]}
        removed += [r["id"] for r in order[n:]]
    pairs = defaultdict(dict)
    for r in by.get("D1P", []) + by.get("D1", []):
        pairs[r.get("pair_id")][r.get("role")] = r
    complete = {k: v for k, v in pairs.items() if k and {"person", "noun"} == set(v)}
    broken = [k for k in pairs if k not in complete]
    if broken:
        errors.append(f"짝이 맞지 않는 pair_id {len(broken)}개")
    bad_pair = lambda k: any(v["id"] in prefer for v in complete[k].values())  # noqa: E731
    if len(complete) < pairs_final:
        errors.append(f"쌍: {len(complete)} < {pairs_final} (부족 {pairs_final - len(complete)})")
    else:
        order = sorted(complete, key=lambda k: (bad_pair(k), _h(k)))
        for k in order[:pairs_final]:
            keep_ids |= {v["id"] for v in complete[k].values()}
        for k in order[pairs_final:]:
            removed += [v["id"] for v in complete[k].values()]
    removed += [v["id"] for k in broken for v in pairs[k].values()]
    if errors:
        return [], sorted(set(removed)), errors
    return [r for r in rows if r["id"] in keep_ids], sorted(set(removed)), []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--removed-out", type=Path, required=True)
    ap.add_argument("--prefer-drop", type=Path)
    a = ap.parse_args(argv)
    rows = [json.loads(x) for x in a.inp.read_text(encoding="utf-8").splitlines() if x.strip()]
    prefer = json.loads(a.prefer_drop.read_text(encoding="utf-8")) if a.prefer_drop else []
    kept, removed, errors = trim(rows, prefer_drop=prefer)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False))
        return 1
    a.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")
    a.removed_out.write_text(json.dumps({"rule": PREFIX, "removed_ids": removed, "count": len(removed)}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "kept": len(kept), "removed": len(removed)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
