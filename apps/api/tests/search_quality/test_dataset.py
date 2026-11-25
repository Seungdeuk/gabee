"""평가셋·핀·정합 검사 시험(DB 불필요). 사례를 바꾸면 핀이 어긋나 실패하고, 잘못된 gold·범위는 평가를 중단시킨다."""

import copy
import json

import pytest

from evals.search_quality import case_specs, data, runner, validate
from evals.search_quality.world import World

CATEGORIES = {
    "exact": 3,
    "multi_keyword": 3,
    "synonym": 3,
    "recency": 2,
    "change": 2,
    "cancel": 1,
    "undecided": 2,
    "no_result": 2,
    "deleted": 1,
    "other_family": 1,
    "direct_room": 2,
    "context": 1,
    "card": 1,
}


def test_there_are_24_cases_with_the_declared_categories_and_frozen_pins():
    cases = case_specs.load()
    assert len(cases) == 24 and len({c["id"] for c in cases}) == 24
    counts: dict[str, int] = {}
    for c in cases:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    assert counts == CATEGORIES
    assert case_specs.check_pins() == []


def test_the_declared_cases_pass_the_consistency_check():
    assert validate.check(case_specs.load()) == []


def test_q23_has_a_history_case_and_a_history_less_diagnostic_and_q24_is_not_a_synonym_case():
    by_id = {c["id"]: c for c in case_specs.load()}
    q23 = by_id["q23"]
    assert q23["history"] and q23["queries"]["no_history"] == ["그거"]
    assert q23["expected_cause"]["no_history"] == "context_needed"
    q24 = by_id["q24"]
    assert q24["card"] and not q24["lexical_gap"]
    assert {q24["expected_cause"]["ideal"], q24["expected_cause"]["naive"]} == {
        "content_not_indexed"
    }


def test_known_limitations_are_declared_not_removed_from_quality():
    known = {c["id"] for c in case_specs.load() if c["known_limitation"]}
    assert known == {"q07", "q08", "q09", "q24"}
    assert all(
        c["gold"] for c in case_specs.load() if c["id"] in known
    )  # 평균에서 빠지지 않고 미검출로 센다


def test_every_unanswerable_case_has_a_bait_outside_the_scope_or_is_a_plain_no_result():
    scope = data.family_scope_keys()
    for c in case_specs.load():
        if c["gold"]:
            continue
        assert all(k not in scope for k in c["forbidden"])
        if c["category"] != "no_result":
            assert c["forbidden"]


def test_the_world_has_no_word_that_would_hide_a_synonym_gap_or_a_context_gap():
    texts = " ".join(m.text for m in data.MESSAGES if m.room == "family")
    for word in ("병원", "그거", "정비", "수영장", "계약금", "가평", "깜짝파티", "성적표"):
        assert word not in texts


def _mutated(mutator):
    cases = copy.deepcopy(case_specs.load())
    mutator({c["id"]: c for c in cases})
    return cases


@pytest.mark.parametrize(
    "mutator, expect",
    [
        (lambda by: by["q01"]["key_facts"].append("없는 사실"), "핵심 사실"),
        (lambda by: by["q01"].update(gold=["d01"]), "검색 범위"),
        (lambda by: by["q01"].update(gold=["m34"]), "검색 범위"),
        (lambda by: by["q20"].update(forbidden=["m10"]), "검색 범위 안"),
        (lambda by: by["q17"]["queries"].update(ideal=["치과"]), "결과 없음"),
        (lambda by: by["q21"].update(forbidden=["m01"]), "미끼"),
        (lambda by: by["q07"]["queries"].update(ideal=["치과"]), "lexical_gap"),
        (lambda by: by["q01"].update(gold=["zz99"]), "선언되지 않은"),
        (lambda by: by["q17"].update(key_facts=["x"]), "key_facts"),
        (lambda by: by["q24"].update(gold=["m01"]), "카드"),
        (lambda by: by["q01"]["expected_cause"].update(ideal="nope"), "알 수 없는 원인"),
    ],
)
def test_invalid_gold_scope_or_facts_are_rejected(mutator, expect):
    problems = validate.check(_mutated(mutator))
    assert any(expect in p for p in problems), problems


def test_tampered_cases_or_pins_stop_the_run_before_any_score(tmp_path, monkeypatch):
    tampered = copy.deepcopy(case_specs.load())
    tampered[0]["gold"] = ["m02"]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(case_specs, "CASES_PATH", path)
    assert any("선언" in p for p in case_specs.check_pins())
    with pytest.raises(validate.DatasetInvalid, match="핀 검사"):
        runner.run(World())


def test_changing_a_world_message_breaks_the_world_pin(monkeypatch):
    changed = tuple(
        data.Msg(**{**m.__dict__, "text": m.text + "!"}) if m.key == "m01" else m
        for m in data.MESSAGES
    )
    monkeypatch.setattr(data, "MESSAGES", changed)
    assert any("world_sha256" in p for p in case_specs.check_pins())
