"""R9 독립 평가셋 자동 검증기: 공통 JSONL 규격 검사, 중복·유사도·누수 검사, SHA256 매니페스트, 검수 표본 id 추출.

**평가셋 원문은 어떤 출력에도 내보내지 않는다.** 보고는 검사 코드, 건수, 문장 id(실패·표본)만 낸다. 평가셋 작성자가 아닌 쪽(학습 데이터 작성 쪽)이
이 도구로 집계만 확인하게 하려는 설계이며, 작성자는 id 로 문제 문장을 찾아 고친다.
규격: docs/security/NER_R9_COMMON_SPEC.md. 사전 등록: docs/security/NER_R9_PREREGISTRATION.md.

사용::

    python validate_r9_evalset.py --data X.jsonl --set-kind representative --report-out report.json \\
        --reference-dir <학습 산출 폴더> ... --manifest-out manifest.json [--strict]
    python validate_r9_evalset.py --data X.jsonl --verify-manifest manifest.json
    python validate_r9_evalset.py --data X.jsonl --make-review-sample 300 --seed 20261120 --review-out ids.json
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

VALIDATOR_VERSION = "r9-1.1"
SPEC_VERSION = "r9-1.1"

LABEL_TO_KIND = {"PERSON": "PERSON", "PERSON_ALIAS": "PERSON", "ADDRESS": "ADDRESS", "PHONE": "PHONE", "EMAIL": "EMAIL", "ACCOUNT": "ACCOUNT"}
CONTEXT_LABELS = {"LOCATION", "ORGANIZATION"}
REQUIRED = {"id": str, "category": str, "text": str, "spans": list, "is_negative": bool, "source": str}
SPAN_REQUIRED = {"start": int, "end": int, "label": str, "mapped_kind": str, "value": str}
OPTIONAL_FIELDS = {"split_set", "stress_types", "primary_stress_type", "template_id", "style", "scenario", "context_entities", "exclude", "exclude_reason", "batch"}
SET_KINDS = ("representative", "stress")
# 취약 유형 코드(사람 포함 문장 / 정답 없는 문장 / 기타 개인정보만)
STRESS_PERSON = ["A1", "A3", "B1", "B2", "C1", "C2", "D3", "D1P"]
STRESS_NEG = ["D1", "D2", "A3N", "GENERIC"]
STRESS_OTHER = ["OTHER"]
STRESS_QUOTA = {"A1": 110, "A3": 90, "B1": 90, "B2": 50, "C1": 60, "C2": 40, "D3": 60, "D1P": 50, "D1": 90, "D2": 50, "A3N": 40, "GENERIC": 20, "OTHER": 50}
TARGETS = {
    "representative": {"total": 1600, "person_sentences": 950, "other_only_sentences": 250, "negative_sentences": 400},
    "stress": {"total": 800, "person_sentences": 550, "other_only_sentences": 50, "negative_sentences": 200},
}
JOSA = set("이가은는을를도만과와랑한에야아의로")
# 정책 r9-1.1: 이름+가족호칭에서 호칭은 보호 구간 밖, PERSON_ALIAS 는 별명 자체만
KIN_TERMS = frozenset("엄마 아빠 어머니 아버지 어머님 아버님 할머니 할아버지 외할머니 외할아버지 누나 언니 오빠 형 동생 삼촌 이모 고모 외삼촌 이모부 고모부 큰아들 작은아들 큰딸 막내딸 막내 아들 딸 시어머니 장모님 큰누나 작은이모 큰엄마 작은엄마 외숙모".split())
KIN_MULTI = frozenset(k for k in KIN_TERMS if len(k) >= 2)


def kin_inside(value):
    """구간 값 안에 가족 호칭이 들어 있는지(값 전체, 공백 토큰, 두 글자 이상 호칭으로 끝남). 한 글자 호칭(형)은 이름 끝 글자와 구분이 안 돼 토큰·전체 일치만 본다."""
    if value in KIN_TERMS or any(t in KIN_TERMS for t in value.split()):
        return True
    return any(value.endswith(k) and len(value) > len(k) for k in KIN_MULTI)


def kin_follows(text, end):
    """span 바로 뒤(접미 '이' 허용, 공백 허용)에 가족 호칭이 이어지는지."""
    rest = text[end:end + 8]
    tail = r"(?=$|[^가-힣]|(?:이랑|이가|께서|한테서|한테|에게|이|가|은|는|을|를|도|의|께|랑|와|과|네|야|아)(?:$|[^가-힣]))"
    m = re.match(r"^(?:이)?\s?(" + "|".join(sorted(KIN_TERMS, key=len, reverse=True)) + r")" + tail, rest)
    return bool(m)

PHONE_RE = re.compile(r"01[016789][-. ]?\d{3,4}[-. ]?\d{4}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
ACCOUNT_RE = re.compile(r"(?<![\d-])(?!(?:19|20)\d\d-\d{1,2}-\d{1,2})\d{2,6}-\d{2,6}-\d{2,8}(?![\d-])")
ADDR_RE = re.compile(r"[가-힣0-9]+(?:로|길)\s?\d+|\d+동\s?\d+호")


def norm(t):
    return re.sub(r"[\s.,!?~ㅋㅎㅠㅜ'\"\-·…]+", "", t)


def skeleton(text, spans):
    out, pos = [], 0
    for s in sorted(spans, key=lambda x: x["start"]):
        out.append(text[pos:s["start"]])
        out.append("§")
        pos = s["end"]
    out.append(text[pos:])
    return norm("".join(out))


def grams(s, n=4):
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Report:
    def __init__(self):
        self.errors = defaultdict(list)  # code -> [id]
        self.warns = defaultdict(list)
        self.info = {}

    def err(self, code, rid):
        self.errors[code].append(rid)

    def warn(self, code, rid):
        self.warns[code].append(rid)

    def to_dict(self, full_ids=False):
        def pack(d):
            out = {}
            for k, v in d.items():
                u = list(dict.fromkeys(v))  # 같은 id 중복 제거(순서 유지)
                out[k] = {"count": len(v), "unique_ids": len(u), "ids": u if full_ids else u[:50]}
            return out
        return {"errors": pack(self.errors), "warnings": pack(self.warns), "info": self.info}


def load_rows(path):
    rows = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            raise SystemExit(f"JSON 파싱 실패: {i}번째 줄")
    return rows


def check_schema(rows, rep, set_kind):
    ids = Counter()
    texts = Counter()
    normed = Counter()
    for r in rows:
        rid = r.get("id", f"<noid:{rows.index(r)}>")
        for k, t in REQUIRED.items():
            if k not in r or not isinstance(r[k], t) or (t is str and not r[k]):
                rep.err("SCHEMA_REQUIRED_FIELD", rid)
        if r.get("exclude") and not isinstance(r.get("exclude_reason"), str):
            rep.err("SCHEMA_EXCLUDE_NEEDS_REASON", rid)
        extra = set(r) - set(REQUIRED) - OPTIONAL_FIELDS
        if extra:
            rep.warn("SCHEMA_UNKNOWN_FIELD", rid)
        if set_kind and r.get("split_set") not in (None, set_kind):
            rep.err("SCHEMA_SPLIT_SET_MISMATCH", rid)
        ids[r.get("id")] += 1
        if isinstance(r.get("text"), str):
            texts[r["text"]] += 1
            normed[norm(r["text"])] += 1
    for r in rows:
        rid = r.get("id")
        if ids[rid] > 1:
            rep.err("DUP_ID", rid)
        if isinstance(r.get("text"), str):
            if texts[r["text"]] > 1:
                rep.err("DUP_TEXT_EXACT", rid)
            elif normed[norm(r["text"])] > 1:
                rep.err("DUP_TEXT_NORMALIZED", rid)


def check_spans(rows, rep):
    for r in rows:
        rid = r.get("id")
        text = r.get("text")
        spans = r.get("spans")
        if r.get("exclude") or not isinstance(text, str) or not isinstance(spans, list):
            continue
        ok_spans = []
        for s in spans:
            bad = False
            for k, t in SPAN_REQUIRED.items():
                if k not in s or not isinstance(s[k], t) or isinstance(s[k], bool):
                    rep.err("SPAN_REQUIRED_FIELD", rid); bad = True
            if bad:
                continue
            if not (0 <= s["start"] < s["end"] <= len(text)):
                rep.err("SPAN_BOUNDS", rid); continue
            if text[s["start"]:s["end"]] != s["value"]:
                rep.err("SPAN_VALUE_MISMATCH", rid); continue
            if s["label"] not in LABEL_TO_KIND:
                rep.err("LABEL_UNKNOWN_OR_FORBIDDEN", rid); continue
            if LABEL_TO_KIND[s["label"]] != s["mapped_kind"]:
                rep.err("MAPPED_KIND_MISMATCH", rid); continue
            if s["value"] != s["value"].strip() or not s["value"].strip():
                rep.err("SPAN_VALUE_WHITESPACE", rid)
            if s["label"] in ("PERSON", "PERSON_ALIAS") and len(s["value"]) == 1:
                rep.err("ONE_CHAR_NAME_MUST_BE_EXCLUDED", rid)
            if s["label"] == "PERSON_ALIAS" and kin_inside(s["value"]):
                rep.err("ALIAS_CONTAINS_KIN_TERM", rid)
            if s["label"] == "PERSON" and kin_inside(s["value"]):
                rep.err("PERSON_CONTAINS_KIN_TERM", rid)
            ok_spans.append(s)
        ss = sorted(ok_spans, key=lambda x: x["start"])
        for a, b in zip(ss, ss[1:]):
            if b["start"] < a["end"]:
                rep.err("SPAN_OVERLAP", rid)
        if bool(spans) == bool(r.get("is_negative")):
            rep.err("NEGATIVE_FLAG_INCONSISTENT", rid)
        for ce in r.get("context_entities") or []:
            try:
                if ce["label"] not in CONTEXT_LABELS or text[ce["start"]:ce["end"]] != ce["value"]:
                    rep.err("CONTEXT_ENTITY_INVALID", rid)
                elif any(max(ce["start"], s["start"]) < min(ce["end"], s["end"]) for s in ok_spans):
                    rep.err("CONTEXT_ENTITY_OVERLAPS_PROTECTED", rid)
            except Exception:
                rep.err("CONTEXT_ENTITY_INVALID", rid)


def check_hidden_pii_and_unlabeled(rows, rep):
    person_vals = {s["value"] for r in rows for s in r.get("spans", []) if s.get("label") in ("PERSON", "PERSON_ALIAS") and len(s.get("value", "")) >= 2}
    for r in rows:
        rid, text = r["id"], r["text"]
        spans = [s for s in r.get("spans", []) if isinstance(s, dict) and "start" in s]
        covered = [False] * len(text)
        for s in spans:
            for i in range(max(0, s["start"]), min(len(text), s["end"])):
                covered[i] = True
        if r.get("is_negative"):
            for name, rx in (("PHONE", PHONE_RE), ("EMAIL", EMAIL_RE), ("ACCOUNT", ACCOUNT_RE), ("ADDRESS", ADDR_RE)):
                if rx.search(text):
                    rep.warn(f"NEGATIVE_HIDDEN_{name}_PATTERN", rid)
        else:
            for name, rx, kind in (("PHONE", PHONE_RE, "PHONE"), ("EMAIL", EMAIL_RE, "EMAIL"), ("ACCOUNT", ACCOUNT_RE, "ACCOUNT"), ("ADDRESS", ADDR_RE, "ADDRESS")):
                for m in rx.finditer(text):
                    if not any(covered[m.start():m.end()]):
                        rep.warn(f"UNLABELED_{name}_PATTERN", rid)
                        break
        # 이 세트의 다른 문장에서 사람 이름으로 라벨된 문자열이 이 문장에 라벨 없이 나오는 경우(정답 누락 의심)
        for v in person_vals:
            i = text.find(v)
            while i >= 0:
                if not any(covered[i:i + len(v)]):
                    rep.warn("UNLABELED_KNOWN_NAME_LEN3PLUS" if len(v) >= 3 else "UNLABELED_KNOWN_NAME_LEN2", rid)
                    break
                i = text.find(v, i + 1)


def span_values(r, labels):
    return [s["value"] for s in r.get("spans", []) if s.get("label") in labels]


def composition(rows, set_kind, rep):
    active = [r for r in rows if not r.get("exclude")]
    n = len(active)
    person_s = [r for r in active if any(s.get("label") in ("PERSON", "PERSON_ALIAS") for s in r["spans"])]
    other_only = [r for r in active if r["spans"] and r not in person_s]
    neg = [r for r in active if r.get("is_negative")]
    spans = [s for r in active for s in r["spans"]]
    person_spans = [s for s in spans if s["label"] in ("PERSON", "PERSON_ALIAS")]
    lens = Counter(len(s["value"]) for s in person_spans)
    vals = [s["value"] for s in person_spans]
    cnt = Counter(vals)
    multi = sum(1 for r in person_s if len(span_values(r, ("PERSON", "PERSON_ALIAS"))) >= 2)
    info = {
        "rows_total": len(rows), "rows_excluded": len(rows) - n, "excluded_reasons": dict(Counter(r.get("exclude_reason") for r in rows if r.get("exclude"))),
        "sentences": n, "person_sentences": len(person_s), "other_only_sentences": len(other_only), "negative_sentences": len(neg),
        "person_spans": len(person_spans), "person_alias_spans": sum(1 for s in person_spans if s["label"] == "PERSON_ALIAS"),
        "labels": dict(Counter(s["label"] for s in spans)),
        "person_len_dist": {str(k): v for k, v in sorted(lens.items())},
        "multi_person_sentences": multi,
        "distinct_person_values": len(cnt), "distinct_ratio": round(len(cnt) / len(vals), 3) if vals else None,
        "max_person_value_reuse": max(cnt.values()) if cnt else 0, "values_reused_over_4": sum(1 for v in cnt.values() if v > 4),
        "categories": dict(Counter(r["category"] for r in active)),
        "styles": dict(Counter(r.get("style") for r in active if r.get("style"))),
        "length_chars": {"min": min((len(r["text"]) for r in active), default=0), "max": max((len(r["text"]) for r in active), default=0),
                         "mean": round(sum(len(r["text"]) for r in active) / n, 1) if n else 0},
    }
    kin_adj = [r["id"] for r in person_s if any(sp["label"] in ("PERSON", "PERSON_ALIAS") and kin_follows(r["text"], sp["end"]) for sp in r["spans"])]
    neg_kin = [r["id"] for r in neg if any(k in r["text"] for k in KIN_MULTI)]
    info["kin_adjacent_person_sentences"] = len(kin_adj)
    info["negatives_with_kin_term"] = len(neg_kin)
    info["person_2char_share_pct"] = round(100 * lens.get(2, 0) / len(person_spans), 1) if person_spans else None
    info["alias_share_pct"] = round(100 * sum(1 for sp in person_spans if sp["label"] == "PERSON_ALIAS") / len(person_spans), 1) if person_spans else None
    info["_kin_adjacent_ids"] = kin_adj
    if set_kind == "representative":
        if len(neg_kin) < 30:
            rep.warn("COMPOSITION_KIN_ONLY_NEGATIVES_BELOW_30", f"{len(neg_kin)}")
        if info["person_2char_share_pct"] is not None and not (25 <= info["person_2char_share_pct"] <= 35):
            rep.warn("COMPOSITION_PERSON_2CHAR_SHARE_OUT_OF_25_35", f"{info['person_2char_share_pct']}")
        if info["alias_share_pct"] is not None and info["alias_share_pct"] < 8:
            rep.warn("COMPOSITION_ALIAS_SHARE_BELOW_8", f"{info['alias_share_pct']}")
    tg = TARGETS.get(set_kind)
    if tg:
        info["targets"] = tg
        for k, key in (("total", "sentences"), ("person_sentences", "person_sentences"), ("other_only_sentences", "other_only_sentences"), ("negative_sentences", "negative_sentences")):
            if info[key] < 0.97 * tg[k] or info[key] > 1.03 * tg[k]:
                rep.warn(f"COMPOSITION_OFF_TARGET_{k.upper()}", f"{info[key]}/{tg[k]}")
    if set_kind == "stress":
        prim = Counter(r.get("primary_stress_type") for r in active)
        info["stress_primary_counts"] = {k: prim.get(k, 0) for k in STRESS_QUOTA}
        info["stress_quota"] = STRESS_QUOTA
        for k, q in STRESS_QUOTA.items():
            if prim.get(k, 0) < 0.9 * q:
                rep.warn("STRESS_QUOTA_SHORT_" + k, f"{prim.get(k, 0)}/{q}")
        missing = [r["id"] for r in active if r.get("primary_stress_type") not in STRESS_QUOTA]
        for rid in missing:
            rep.err("STRESS_PRIMARY_TYPE_MISSING_OR_UNKNOWN", rid)
        # 유형별 형식 일관성(경고): 유형 정의와 span 구조가 어긋난 문장
        for r in active:
            t = r.get("primary_stress_type")
            ps = sorted([s for s in r["spans"] if s["label"] in ("PERSON", "PERSON_ALIAS")], key=lambda s: s["start"])
            text = r["text"]
            nxt = lambda s: text[s["end"]] if s["end"] < len(text) else ""
            if t == "A1" and not (ps and all(len(s["value"]) == 2 for s in ps[:1])):
                rep.warn("TYPE_CONSISTENCY_A1_NOT_2CHAR", r["id"])
            if t == "B1" and not (ps and 3 <= len(ps[0]["value"]) <= 5 and (nxt(ps[0]) == "" or nxt(ps[0]) in " ,.!?~ㅋㅎ")):
                rep.warn("TYPE_CONSISTENCY_B1", r["id"])
            if t == "C1" and not (ps and any(nxt(s) in JOSA for s in ps)):
                rep.warn("TYPE_CONSISTENCY_C1_NO_JOSA", r["id"])
            if t in ("C2",) and not (len(ps) >= 2 and any(b["start"] - a["end"] <= 1 for a, b in zip(ps, ps[1:]))):
                rep.warn("TYPE_CONSISTENCY_C2_NOT_ADJACENT", r["id"])
            if t == "D3" and len(ps) < 2:
                rep.warn("TYPE_CONSISTENCY_D3_SINGLE", r["id"])
            if t in STRESS_NEG and not r["is_negative"]:
                rep.warn("TYPE_CONSISTENCY_NEG_TYPE_HAS_SPAN", r["id"])
            if t in STRESS_PERSON and not ps:
                rep.warn("TYPE_CONSISTENCY_PERSON_TYPE_NO_PERSON", r["id"])
            if t == "A3N" and not r.get("context_entities"):
                rep.warn("TYPE_CONSISTENCY_A3N_NO_CONTEXT_ENTITY", r["id"])
    return info, active


def within_set_similarity(active, rep, info):
    skels = {r["id"]: skeleton(r["text"], r["spans"]) for r in active}
    cnt = Counter(skels.values())
    dup_rows = [rid for rid, s in skels.items() if cnt[s] > 2]
    for rid in dup_rows:
        rep.warn("SKELETON_REPEATED_OVER_2", rid)
    gs = {rid: grams(s) for rid, s in skels.items()}
    index = defaultdict(list)
    for rid, g in gs.items():
        for x in g:
            index[x].append(rid)
    near = set()
    for rid, g in gs.items():
        if not g:
            continue
        share = Counter()
        for x in g:
            for o in index[x]:
                if o != rid:
                    share[o] += 1
        for o, c in share.items():
            if c >= 0.7 * len(g) and len(g & gs[o]) / len(g | gs[o]) >= 0.7:
                near.add(rid)
                break
    for rid in near:
        rep.warn("NEAR_DUPLICATE_WITHIN_SET_4GRAM_GE_0.7", rid)
    info["within_set"] = {"skeleton_distinct": len(cnt), "rows_with_skeleton_repeated_over_2": len(dup_rows), "rows_with_near_duplicate_partner": len(near),
                          "near_duplicate_share": round(len(near) / max(1, len(active)), 4)}
    if len(near) > 0.03 * len(active):
        rep.err("NEAR_DUPLICATE_SHARE_OVER_3PCT", f"{len(near)}/{len(active)}")


def reference_rows(paths):
    """참조 코퍼스(학습·개발·소비된 평가셋)에서 (정규화 문장, 틀, 이름) 을 모은다. 내용은 출력하지 않는다."""
    sents, skels, names, skel_by_gram = set(), {}, set(), defaultdict(list)
    n_files = n_rows = 0
    for p in paths:
        p = Path(p)
        files = [p] if p.is_file() else sorted(p.rglob("*.jsonl"))
        for f in files:
            n_files += 1
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                t = o.get("text")
                if not isinstance(t, str):
                    continue
                n_rows += 1
                sents.add(norm(t))
                spans = []
                for s in o.get("spans", []) or []:
                    if isinstance(s, dict) and "start" in s and "end" in s:
                        spans.append({"start": s["start"], "end": s["end"]})
                        lab = s.get("label") or s.get("kind")
                        if lab in ("PERSON", "PERSON_ALIAS") and 0 <= s["start"] < s["end"] <= len(t):
                            names.add(t[s["start"]:s["end"]])
                if len(t) <= 80:
                    sk = skeleton(t, spans)
                    if sk not in skels:
                        skels[sk] = True
                        for g in grams(sk):
                            skel_by_gram[g].append(sk)
    return {"sents": sents, "skels": skels, "names": names, "index": skel_by_gram, "n_files": n_files, "n_rows": n_rows}


def against_reference(active, ref, rep, info):
    exact = skel_eq = sim = 0
    seen_rows = []
    for r in active:
        n = norm(r["text"])
        if n in ref["sents"]:
            rep.err("LEAK_SENTENCE_EQUALS_REFERENCE", r["id"]); exact += 1
        sk = skeleton(r["text"], r["spans"])
        if sk in ref["skels"]:
            rep.warn("LEAK_SKELETON_EQUALS_REFERENCE", r["id"]); skel_eq += 1
        g = grams(sk)
        if g:
            share = Counter()
            for x in g:
                for o in ref["index"].get(x, ()):
                    share[o] += 1
            if any(c >= 0.6 * len(g) and len(g & grams(o)) / len(g | grams(o)) >= 0.6 for o, c in share.most_common(30)):
                rep.warn("LEAK_SKELETON_SIMILAR_TO_REFERENCE_4GRAM_GE_0.6", r["id"]); sim += 1
        vals = span_values(r, ("PERSON", "PERSON_ALIAS"))
        if vals and any(v in ref["names"] for v in vals):
            seen_rows.append(r["id"])
    n = max(1, len(active))
    info["reference"] = {"files": ref["n_files"], "rows": ref["n_rows"], "sentence_equal_rows": exact, "skeleton_equal_rows": skel_eq,
                         "skeleton_similar_rows": sim, "rows_with_name_seen_in_reference": len(seen_rows), "name_seen_share": round(len(seen_rows) / n, 4)}
    if skel_eq > 0.02 * n:
        rep.err("LEAK_SKELETON_EQUAL_OVER_2PCT", f"{skel_eq}/{n}")
    if sim > 0.03 * n:
        rep.err("LEAK_SKELETON_SIMILAR_OVER_3PCT", f"{sim}/{n}")
    return seen_rows


def make_manifest(path, rows, rep, set_kind, extra):
    errs = sum(len(v) for v in rep.errors.values())
    return {"dataset": Path(path).name, "set_kind": set_kind, "rows": len(rows), "sha256": sha256_file(path),
            "validator_version": VALIDATOR_VERSION, "spec_version": SPEC_VERSION, "validated_at": datetime.now(timezone.utc).isoformat(),
            "errors_total": errs, "errors": {k: len(v) for k, v in rep.errors.items()}, "warnings": {k: len(v) for k, v in rep.warns.items()}, **extra}


def review_sample(rows, n, seed):
    """층화 무작위 표본 + 고위험 추가 검수 id. 원문은 내보내지 않는다."""
    import random
    rng = random.Random(seed)
    active = [r for r in rows if not r.get("exclude")]
    groups = defaultdict(list)
    for r in active:
        groups[(r.get("split_set"), r.get("primary_stress_type") or r["category"])].append(r["id"])
    total = len(active)
    picked = set()
    for k, ids in sorted(groups.items(), key=lambda kv: str(kv[0])):
        take = max(1, round(n * len(ids) / total))
        picked.update(rng.sample(ids, min(take, len(ids))))
    while len(picked) < n:
        picked.add(rng.choice([r["id"] for r in active]))
    high = []
    for r in active:
        ps = span_values(r, ("PERSON", "PERSON_ALIAS"))
        risk = (len(ps) >= 2 or r.get("primary_stress_type") in ("A3", "A3N", "D1", "D1P", "D2", "C2", "D3")
                or any(s["label"] == "PERSON_ALIAS" for s in r["spans"]) or bool(r.get("context_entities")))
        if risk:
            high.append(r["id"])
    high_extra = [i for i in high if i not in picked]
    rng.shuffle(high_extra)
    return {"seed": seed, "random_stratified_ids": sorted(picked), "high_risk_candidate_count": len(high), "high_risk_extra_ids": sorted(high_extra[: max(100, n // 2)])}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--set-kind", choices=SET_KINDS)
    ap.add_argument("--reference-dir", action="append", default=[], type=Path)
    ap.add_argument("--report-out", type=Path)
    ap.add_argument("--manifest-out", type=Path)
    ap.add_argument("--annotations-out", type=Path, help="이름이 참조 코퍼스에 있는 문장 id(층화 보고용)")
    ap.add_argument("--verify-manifest", type=Path)
    ap.add_argument("--make-review-sample", type=int)
    ap.add_argument("--review-out", type=Path)
    ap.add_argument("--seed", type=int, default=20261120)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--full-ids", action="store_true", help="보고서에 문장 id 전체를 저장(기본은 코드당 50개)")
    a = ap.parse_args(argv)

    if a.verify_manifest:
        m = json.loads(a.verify_manifest.read_text(encoding="utf-8"))
        ok = m["sha256"] == sha256_file(a.data)
        print(json.dumps({"sha256_matches_manifest": ok, "rows_in_manifest": m["rows"]}))
        return 0 if ok else 1

    rows = load_rows(a.data)
    if a.make_review_sample:
        out = review_sample(rows, a.make_review_sample, a.seed)
        if a.review_out:
            a.review_out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"random_stratified": len(out["random_stratified_ids"]), "high_risk_extra": len(out["high_risk_extra_ids"]), "high_risk_candidates": out["high_risk_candidate_count"]}))
        return 0

    rep = Report()
    check_schema(rows, rep, a.set_kind)
    structural_errors = sum(len(v) for v in rep.errors.values())
    check_spans(rows, rep)
    rows_ok = [r for r in rows if all(k in r for k in REQUIRED) and isinstance(r["text"], str) and isinstance(r["spans"], list)]
    check_hidden_pii_and_unlabeled([r for r in rows_ok if not r.get("exclude")], rep)
    info, active = composition(rows_ok, a.set_kind, rep)
    within_set_similarity(active, rep, info)
    seen = []
    if a.reference_dir:
        ref = reference_rows(a.reference_dir)
        seen = against_reference(active, ref, rep, info)
    kin_adj_ids = info.pop("_kin_adjacent_ids", [])
    rep.info = info
    result = rep.to_dict(a.full_ids)
    if a.report_out:
        a.report_out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.annotations_out:
        a.annotations_out.write_text(json.dumps({"name_seen_in_reference": sorted(seen), "kin_adjacent_person_sentences": sorted(kin_adj_ids)}, ensure_ascii=False), encoding="utf-8")
    if a.manifest_out:
        a.manifest_out.write_text(json.dumps(make_manifest(a.data, rows, rep, a.set_kind, {"info": info}), ensure_ascii=False, indent=1), encoding="utf-8")
    n_err = sum(len(v) for v in rep.errors.values())
    n_warn = sum(len(v) for v in rep.warns.values())
    print(json.dumps({"rows": len(rows), "errors": {k: len(v) for k, v in rep.errors.items()}, "warnings": {k: len(v) for k, v in rep.warns.items()},
                      "sentences": info["sentences"], "person_spans": info["person_spans"], "negatives": info["negative_sentences"]}, ensure_ascii=False))
    return 1 if (a.strict and n_err) else 0


if __name__ == "__main__":
    sys.exit(main())
