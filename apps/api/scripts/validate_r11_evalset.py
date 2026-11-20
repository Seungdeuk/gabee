"""R11 독립 평가셋 검증기(`validate_r9_evalset.py` 확장 래퍼). 사양 `NER_R11_EVALSET_SPEC.md` §3·§4·§11.

기본 검사(스키마, span 무결성, 중복·유사도, 참조 집합 누수, 매니페스트, 검수 표본)는 R9 검증기를 그대로 쓰고, R11 에서 더해진 것만 확장한다.
 - 필드: pair_id·role·pair_word·mix_kind(선택 필드로 허용, 규칙은 아래)
 - 유형 값 집합과 스트레스 목표(2,350문장: 사람 1,800 / 기타만 50 / 개인정보 없음 500)
 - pair 무결성(규칙 1~9), 쌍 수 300 이상·서로 다른 단어 75 이상·단어당 최대 4쌍
 - LONGNAME(4글자 이상 구간, 조사 있음/없음 각 40 이상, 총 120 이상), ORGLOC_MIX(문장 안 LOC/ORG 와 PERSON 이 함께, mix_kind 별 30 이상, 총 100 이상)
**평가셋 원문은 출력하지 않는다**(코드·건수·id 만). 사용법은 R9 검증기와 같다: python validate_r11_evalset.py --data X.jsonl --set-kind stress --report-out report.json ... [--strict]
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_r9_evalset as base  # noqa: E402

VALIDATOR_VERSION = "r11-1.0"
SPEC_VERSION = "r11-1.0"
NEW_TYPES = ["NEWNAME", "LONGNAME", "ORGLOC_MIX"]
ALLOWED_TYPES = set(base.STRESS_PERSON) | set(base.STRESS_NEG) | set(base.STRESS_OTHER) | set(NEW_TYPES)
MIX_KINDS = {"name_looks_place", "place_looks_name", "plain"}
PERSON = ("PERSON", "PERSON_ALIAS")
R11_STRESS_QUOTA = {"A1": 150, "A3": 100, "B1": 240, "B2": 80, "C1": 100, "C2": 200, "D3": 100, "D1P": 300, "D1": 300, "D2": 100, "A3N": 60, "GENERIC": 40,
                    "OTHER": 50, "NEWNAME": 310, "LONGNAME": 120, "ORGLOC_MIX": 100}
LIMITS = {"pairs_min": 300, "distinct_words_min": 75, "max_pairs_per_word": 4, "longname_total": 120, "longname_each": 40, "mix_total": 100, "mix_each": 30}


def _persons(r):
    return [s for s in r["spans"] if s.get("label") in PERSON]


def check_r11_extras(active, rep):
    """pair·LONGNAME·ORGLOC_MIX·유형 값 검사. 반환: 보고용 요약 dict(원문 없음)."""
    info = {}
    # 유형 값 집합
    for r in active:
        for t in [r.get("primary_stress_type"), *(r.get("stress_types") or [])]:
            if t is not None and t not in ALLOWED_TYPES:
                rep.err("R11_TYPE_NOT_ALLOWED", r["id"])
    # pair 필드 스키마
    pair_rows = defaultdict(list)
    for r in active:
        has = [k for k in ("pair_id", "role", "pair_word") if r.get(k) not in (None, "")]
        if r.get("role") in ("person", "noun"):
            if len(has) != 3:
                rep.err("R11_PAIR_FIELDS_INCOMPLETE", r["id"])
            pair_rows[r.get("pair_id")].append(r)
        elif has:
            rep.err("R11_PAIR_FIELDS_ON_NON_PAIR_ROW", r["id"])
    words = defaultdict(int)
    n_pairs = 0
    for pid, rs in pair_rows.items():
        roles = Counter(r["role"] for r in rs)
        if roles != Counter({"person": 1, "noun": 1}):
            for r in rs:
                rep.err("R11_PAIR_NOT_ONE_PERSON_ONE_NOUN", r["id"])  # 규칙 1
            continue
        n_pairs += 1
        p = next(r for r in rs if r["role"] == "person")
        n = next(r for r in rs if r["role"] == "noun")
        w = p["pair_word"]
        words[w] += 1
        if n["pair_word"] != w or w not in p["text"] or w not in n["text"]:
            rep.err("R11_PAIR_WORD_MISMATCH", p["id"])  # 규칙 2
        if len(w) < 2:
            rep.err("R11_PAIR_WORD_ONE_CHAR", p["id"])  # 규칙 9
        if not any(s["value"] == w or s["value"].endswith(w) for s in _persons(p)):
            rep.err("R11_PAIR_PERSON_SENTENCE_WITHOUT_WORD_SPAN", p["id"])  # 규칙 3
        if _persons(n):
            rep.err("R11_PAIR_NOUN_SENTENCE_HAS_PERSON", n["id"])  # 규칙 4
        if base.norm(p["text"]) == base.norm(n["text"]):
            rep.err("R11_PAIR_IDENTICAL_TEXT", p["id"])  # 규칙 5
        sp, sn = base.skeleton(p["text"], p["spans"]), base.skeleton(n["text"], n["spans"])
        gp, gn = base.grams(sp), base.grams(sn)
        jac = len(gp & gn) / len(gp | gn) if gp and gn else 0.0
        if sp == sn or jac >= 0.7:
            rep.err("R11_PAIR_TEMPLATES_TOO_SIMILAR", p["id"])  # 규칙 6
        if p.get("primary_stress_type") != "D1P" or n.get("primary_stress_type") != "D1":
            rep.err("R11_PAIR_STRESS_TYPE_NOT_D1P_D1", p["id"])
    info["pairs"] = {"pairs": n_pairs, "distinct_words": len(words), "max_pairs_per_word": max(words.values()) if words else 0}
    if n_pairs < LIMITS["pairs_min"]:
        rep.err("R11_PAIR_COUNT_BELOW_300", f"{n_pairs}")
    if len(words) < LIMITS["distinct_words_min"]:
        rep.err("R11_PAIR_DISTINCT_WORDS_BELOW_75", f"{len(words)}")
    over = [w for w, c in words.items() if c > LIMITS["max_pairs_per_word"]]
    if over:
        rep.err("R11_PAIR_WORD_OVER_4_PAIRS", f"{len(over)} words")  # 단어는 출력하지 않는다
    d1p = sum(1 for r in active if r.get("primary_stress_type") == "D1P")
    d1 = sum(1 for r in active if r.get("primary_stress_type") == "D1")
    if d1p != d1 or d1p != n_pairs:
        rep.err("R11_D1P_D1_COUNT_NOT_EQUAL_PAIRS", f"{d1p}/{d1}/{n_pairs}")
    # LONGNAME
    ln = [r for r in active if r.get("primary_stress_type") == "LONGNAME"]
    with_j = without_j = 0
    for r in ln:
        long_spans = [s for s in _persons(r) if len(s["value"]) >= 4]
        if not long_spans:
            rep.err("R11_LONGNAME_WITHOUT_4PLUS_SPAN", r["id"])
            continue
        nxt = r["text"][long_spans[0]["end"]] if long_spans[0]["end"] < len(r["text"]) else ""
        if nxt and nxt in base.JOSA:
            with_j += 1
        else:
            without_j += 1
    info["longname"] = {"sentences": len(ln), "with_particle": with_j, "without_particle": without_j}
    if len(ln) < LIMITS["longname_total"]:
        rep.err("R11_LONGNAME_BELOW_120", f"{len(ln)}")
    if with_j < LIMITS["longname_each"] or without_j < LIMITS["longname_each"]:
        rep.err("R11_LONGNAME_PARTICLE_SPLIT_BELOW_40", f"{with_j}/{without_j}")
    # ORGLOC_MIX
    mix = [r for r in active if r.get("primary_stress_type") == "ORGLOC_MIX"]
    kinds = Counter()
    for r in mix:
        ctx = [c for c in (r.get("context_entities") or []) if c.get("label") in base.CONTEXT_LABELS]
        ps = _persons(r)
        if not ctx or not ps:
            rep.err("R11_ORGLOC_MIX_NEEDS_CONTEXT_AND_PERSON", r["id"])
        for c in ctx:
            if any(max(c["start"], s["start"]) < min(c["end"], s["end"]) for s in ps):
                rep.err("R11_ORGLOC_MIX_CONTEXT_OVERLAPS_PERSON", r["id"])
        mk = r.get("mix_kind")
        if mk not in MIX_KINDS:
            rep.err("R11_ORGLOC_MIX_KIND_MISSING_OR_UNKNOWN", r["id"])
        kinds[mk] += 1
    info["orgloc_mix"] = {"sentences": len(mix), "mix_kind": dict(kinds)}
    if len(mix) < LIMITS["mix_total"]:
        rep.err("R11_ORGLOC_MIX_BELOW_100", f"{len(mix)}")
    for k in ("name_looks_place", "place_looks_name"):
        if kinds.get(k, 0) < LIMITS["mix_each"]:
            rep.err(f"R11_ORGLOC_MIX_{k.upper()}_BELOW_30", f"{kinds.get(k, 0)}")
    # 한 글자 이름
    for r in active:
        for s in _persons(r):
            if len(s["value"]) < 2:
                rep.err("R11_ONE_CHAR_PERSON", r["id"])
    return info


def install():
    """R9 검증기의 상수·함수를 R11 규격으로 바꾼다(같은 프로세스 안에서만)."""
    base.OPTIONAL_FIELDS |= {"pair_id", "role", "pair_word", "mix_kind"}
    base.STRESS_PERSON[:] = ["A1", "A3", "B1", "B2", "C1", "C2", "D3", "D1P", "NEWNAME", "LONGNAME", "ORGLOC_MIX"]
    base.STRESS_QUOTA.clear()
    base.STRESS_QUOTA.update(R11_STRESS_QUOTA)
    base.TARGETS["stress"] = {"total": 2350, "person_sentences": 1800, "other_only_sentences": 50, "negative_sentences": 500}
    base.VALIDATOR_VERSION, base.SPEC_VERSION = VALIDATOR_VERSION, SPEC_VERSION
    orig = base.composition

    def composition(rows, set_kind, rep):
        info, active = orig(rows, set_kind, rep)
        if set_kind == "stress":
            info["r11"] = check_r11_extras(active, rep)
        return info, active

    base.composition = composition


def main(argv=None):
    install()
    return base.main(argv)


if __name__ == "__main__":
    sys.exit(main())
