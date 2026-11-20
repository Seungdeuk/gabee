"""R11 독립 평가셋 검증기 확장 시험(합성 행만 사용, 실제 평가셋 문장 없음)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_r11_evalset as v  # noqa: E402


class Rep:
    def __init__(self):
        self.errors, self.warns = [], []

    def err(self, code, rid=None):
        self.errors.append((code, rid))

    def warn(self, code, rid=None):
        self.warns.append((code, rid))

    def codes(self):
        return {c for c, _ in self.errors}


def row(i, text, spans, ptype, **kw):
    sp = [{"start": a, "end": b, "label": lab, "mapped_kind": "PERSON", "value": text[a:b]} for a, b, lab in spans]
    return {"id": i, "category": "c", "text": text, "spans": sp, "is_negative": not sp, "source": "synthetic", "primary_stress_type": ptype, "stress_types": [ptype], **kw}


def pair(k, word="가나다", pt=None, nt=None, **over):
    pt = pt or f"{word}가 오늘 ZZ{k} 도착했어"
    nt = nt or f"저기 {word} 위로 YY{k} 구름이 지나가네 정말"
    a = pt.index(word)
    p = row(f"p{k}", pt, [(a, a + len(word), "PERSON")], "D1P", pair_id=f"pp{k}", role="person", pair_word=word)
    n = row(f"n{k}", nt, [], "D1", pair_id=f"pp{k}", role="noun", pair_word=word)
    p.update(over.get("p", {}))
    n.update(over.get("n", {}))
    return [p, n]


def run(rows):
    rep = Rep()
    info = v.check_r11_extras(rows, rep)
    return rep, info


def test_valid_pair_has_no_pair_integrity_errors():
    rep, info = run(pair(1))
    integ = {c for c in rep.codes() if c.startswith("R11_PAIR_") and c not in ("R11_PAIR_COUNT_BELOW_300", "R11_PAIR_DISTINCT_WORDS_BELOW_75")}
    assert not integ, integ
    assert info["pairs"]["pairs"] == 1


def test_noun_sentence_with_person_and_identical_text_and_missing_word_are_errors():
    assert "R11_PAIR_NOUN_SENTENCE_HAS_PERSON" in run(pair(1, n={"spans": [{"start": 3, "end": 5, "label": "PERSON", "mapped_kind": "PERSON", "value": "XY"}]}))[0].codes()
    same = "가나다 아주 좋은 날이다 오늘"
    assert "R11_PAIR_IDENTICAL_TEXT" in run(pair(2, pt=same, nt=same))[0].codes()
    assert "R11_PAIR_WORD_MISMATCH" in run(pair(3, n={"pair_word": "라마바"}))[0].codes()


def test_pair_with_two_person_sentences_is_not_one_person_one_noun():
    a, b = pair(1)
    b["role"] = "person"
    assert "R11_PAIR_NOT_ONE_PERSON_ONE_NOUN" in run([a, b])[0].codes()


def test_pair_fields_on_non_pair_row_and_incomplete_fields():
    r = row("x", "가나 다라", [], "GENERIC", pair_id="q")
    assert "R11_PAIR_FIELDS_ON_NON_PAIR_ROW" in run([r])[0].codes()
    p = pair(1)[0]
    p.pop("pair_word")
    assert "R11_PAIR_FIELDS_INCOMPLETE" in run([p])[0].codes()


def test_counts_pairs_below_300_distinct_words_and_over_4_pairs():
    rows = [r for k in range(5) for r in pair(k, word="가나다")]  # 같은 단어 5쌍
    codes = run(rows)[0].codes()
    assert {"R11_PAIR_COUNT_BELOW_300", "R11_PAIR_DISTINCT_WORDS_BELOW_75", "R11_PAIR_WORD_OVER_4_PAIRS"} <= codes


def test_type_not_allowed_and_one_char_pair_word():
    assert "R11_TYPE_NOT_ALLOWED" in run([row("t", "가나 다라", [], "WRONGTYPE")])[0].codes()
    p, n = pair(1, word="가", pt="가가 간다 ZZ1 오늘 아침에", nt="저기 가 YY1 구름이 지나가네 정말")
    assert "R11_PAIR_WORD_ONE_CHAR" in run([p, n])[0].codes()


def test_longname_requires_4plus_span_and_reports_particle_split():
    ok = row("l1", "남궁민수가 왔다", [(0, 4, "PERSON")], "LONGNAME")
    ok2 = row("l2", "남궁민수 왔다", [(0, 4, "PERSON")], "LONGNAME")
    short = row("l3", "민수가 왔다", [(0, 2, "PERSON")], "LONGNAME")
    rep, info = run([ok, ok2, short])
    assert ("R11_LONGNAME_WITHOUT_4PLUS_SPAN", "l3") in rep.errors
    assert info["longname"] == {"sentences": 3, "with_particle": 1, "without_particle": 1}
    assert "R11_LONGNAME_BELOW_120" in rep.codes()


def test_orgloc_mix_needs_context_person_and_kind_and_no_overlap():
    text = "서울병원에서 민수를 만났다"
    good = row("m1", text, [(7, 9, "PERSON")], "ORGLOC_MIX", mix_kind="plain", context_entities=[{"start": 0, "end": 4, "label": "ORGANIZATION", "value": "서울병원"}])
    nokind = row("m2", text, [(7, 9, "PERSON")], "ORGLOC_MIX", context_entities=[{"start": 0, "end": 4, "label": "ORGANIZATION", "value": "서울병원"}])
    noctx = row("m3", text, [(7, 9, "PERSON")], "ORGLOC_MIX", mix_kind="plain")
    overlap = row("m4", text, [(0, 2, "PERSON")], "ORGLOC_MIX", mix_kind="plain", context_entities=[{"start": 0, "end": 4, "label": "ORGANIZATION", "value": "서울병원"}])
    rep, _ = run([good, nokind, noctx, overlap])
    assert ("R11_ORGLOC_MIX_KIND_MISSING_OR_UNKNOWN", "m2") in rep.errors
    assert ("R11_ORGLOC_MIX_NEEDS_CONTEXT_AND_PERSON", "m3") in rep.errors
    assert ("R11_ORGLOC_MIX_CONTEXT_OVERLAPS_PERSON", "m4") in rep.errors
    assert ("R11_ORGLOC_MIX_NEEDS_CONTEXT_AND_PERSON", "m1") not in rep.errors


def test_install_sets_r11_targets_and_types():
    v.install()
    assert v.base.TARGETS["stress"]["total"] == 2350 and sum(v.base.STRESS_QUOTA.values()) == 2350
    assert {"LONGNAME", "ORGLOC_MIX", "NEWNAME"} <= set(v.base.STRESS_QUOTA)
    assert v.base.STRESS_QUOTA["D1P"] == v.base.STRESS_QUOTA["D1"] == 300 and "pair_id" in v.base.OPTIONAL_FIELDS
