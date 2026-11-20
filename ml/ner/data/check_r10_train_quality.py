"""R10 신규 학습 데이터 품질·중복·유사도 검사(원문 미출력, 건수만). R9 봉인 평가셋은 읽지 않는다.

대상: data_r10/r10_full_train + r10_val_extra. 비교 대상: R9 학습·검증(baseline/synth/r9_Ffull/r9_val_extra), R9 개발 평가셋(R8 하니스의 개발 세트), 세트 내부.
출력: 보고서 JSON(--out).
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_r8_data as r8
import build_r10_data as b10
import build_r9_data as b9

R10 = b10.OUT_DEFAULT
R9 = b10.R9_DIR


def read(p):
    return r8.read_jsonl(p)


def person_vals(rows):
    out = []
    for r in rows:
        for s in r["spans"]:
            if s.get("label") in ("PERSON", "PERSON_ALIAS"):
                out.append(r["text"][s["start"] : s["end"]])
    return out


def jacc(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def near_dup_share(rows, ref_rows, thr):
    """rows 중 ref_rows 와 문장 틀 4-gram Jaccard >= thr 인 비율."""
    idx, grams = defaultdict(list), []
    for r in ref_rows:
        sk = r8.skeleton_of(r["text"], [{"start": s["start"], "end": s["end"]} for s in r["spans"]])
        g = r8.ngrams(sk)
        grams.append(g)
        for x in g:
            idx[x].append(len(grams) - 1)
    hit = 0
    for r in rows:
        sk = r8.skeleton_of(r["text"], [{"start": s["start"], "end": s["end"]} for s in r["spans"]])
        g = r8.ngrams(sk)
        if not g:
            continue
        share = Counter()
        for x in g:
            for i in idx.get(x, ()):
                share[i] += 1
        if any(jacc(g, grams[i]) >= thr for i, _ in share.most_common(30)):
            hit += 1
    return hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=R10 / "r10_quality_report.json")
    a = ap.parse_args()
    tr = read(R10 / "r10_full_train.jsonl")
    va = read(R10 / "r10_val_extra.jsonl")
    allr = tr + va
    ref9 = []
    for f in b10.BASE_FILES + b10.R9_NEW_FILES:
        ref9 += read(R9 / f"{f}.jsonl")
    # 개발 평가셋
    dev_rows = []
    for f in list(r8.EVAL_DIR.rglob("*.jsonl")) + list(r8.NEMO_DIR.glob("*.jsonl")):
        for r in read(f):
            if isinstance(r.get("text"), str) and "spans" in r:
                dev_rows.append(r)
    n9 = {r8.norm(r["text"]) for r in ref9}
    ndev = {r8.norm(r["text"]) for r in dev_rows}
    nn = [r8.norm(r["text"]) for r in allr]
    skel = Counter(
        r8.skeleton_of(r["text"], [{"start": s["start"], "end": s["end"]} for s in r["spans"]]) for r in allr
    )
    pv = person_vals(tr)
    r9v = person_vals(ref9)
    r9_given = set()
    for v in r9v:
        r9_given |= b10.given_parts(v)
    devv = person_vals(dev_rows)
    dev_given = set()
    for v in devv:
        dev_given |= b10.given_parts(v)
    val_vals = set(person_vals(va))
    trs = set(pv)
    frame_use = Counter(r["template_id"] for r in tr)
    pair_rows = [r for r in tr if r.get("pair_id")]
    pw = Counter(r["pair_word"] for r in pair_rows if r["pair_role"] == "person")
    rep = {
        "rows": {"train": len(tr), "val_monitor": len(va)},
        "by_bucket": dict(Counter(r["train_bucket"] for r in tr)),
        "negatives": sum(1 for r in tr if not r["spans"]),
        "exact_dup_within": len(nn) - len(set(nn)),
        "exact_match_with_r9_train": sum(1 for r in allr if r8.norm(r["text"]) in n9),
        "exact_match_with_dev_sets": sum(1 for r in allr if r8.norm(r["text"]) in ndev),
        "skeleton_dup_rows_over_2": sum(c - 2 for c in skel.values() if c > 2),
        "frame_reuse_max": max(frame_use.values()),
        "frame_reuse_gt2": sum(1 for c in frame_use.values() if c > 2),
        "near_dup_4gram_ge0.7_vs_r9_train": near_dup_share(tr, ref9, 0.7),
        "near_dup_4gram_ge0.7_vs_dev": near_dup_share(tr, dev_rows, 0.7),
        "near_dup_4gram_ge0.7_within": near_dup_share(tr, [r for r in tr], 0.7) - len(tr),
        "person_values": {
            "total": len(pv),
            "distinct": len(set(pv)),
            "max_reuse": max(Counter(pv).values()),
            "len_dist": dict(sorted(Counter(len(v) for v in pv).items())),
        },
        "name_overlap": {
            "train_values_in_r9_train_values": len(trs & set(r9v)),
            "train_given_in_r9_given": len({g for v in trs for g in b10.given_parts(v)} & r9_given),
            "train_given_in_dev_given": len({g for v in trs for g in b10.given_parts(v)} & dev_given),
            "train_vs_val_monitor_value_overlap": len(trs & val_vals),
            "reserved_given_in_train(len2 whole, len3 v[1:], len4 v[1:] and v[2:] both)": sum(
                1
                for v in trs
                if (len(v) == 2 and b10.reserved(v))
                or (len(v) == 3 and b10.reserved(v[1:]))
                or (len(v) >= 4 and b10.reserved(v[1:]) and b10.reserved(v[2:]))
            ),
        },
        "d1p_pairs": {
            "person_rows": sum(1 for r in pair_rows if r["pair_role"] == "person"),
            "noun_rows": sum(1 for r in pair_rows if r["pair_role"] == "noun"),
            "distinct_words": len(pw),
            "max_word_uses": max(pw.values()),
            "person_rows_with_span": sum(1 for r in pair_rows if r["pair_role"] == "person" and r["spans"]),
            "noun_rows_with_person_span": sum(
                1
                for r in pair_rows
                if r["pair_role"] == "noun"
                and any(s["label"] in ("PERSON", "PERSON_ALIAS") for s in r["spans"])
            ),
        },
        "kin_inside_label": sum(
            1
            for r in allr
            for s in r["spans"]
            if s["label"] in ("PERSON", "PERSON_ALIAS") and b9.conv.kin_inside(r["text"][s["start"] : s["end"]])
        ),
        "one_char_person": sum(1 for r in allr for s in r["spans"] if s["label"] in ("PERSON", "PERSON_ALIAS") and s["end"] - s["start"] < 2),
    }
    a.out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
