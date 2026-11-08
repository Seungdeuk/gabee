"""평가 질문 생성(evals/location/gen_questions.py)과 조각 단위 분리 시험. LLM 은 가짜로 바꾼다."""

import json
from collections import defaultdict
from types import SimpleNamespace

import pytest

from evals import budget
from evals.location import gen_questions as gq
from evals.location import scenarios as sc
from evals.location.validate import check_scenario


def _all_chunks():
    return [(name, c) for name, s in sc.load_all() for c in sc.chunks_of(s)]


def test_every_scenario_is_valid_and_ids_do_not_collide():
    people, places = set(), set()
    for name, s in sc.load_all():
        assert check_scenario(s) == [], name
        ids_p = {p["id"] for p in s["people"]}
        ids_l = {p["id"] for p in s["places"]}
        assert not (people & ids_p) and not (places & ids_l), f"{name}: id 가 다른 시나리오와 겹침"
        people |= ids_p
        places |= ids_l
    assert len(sc.load_all()) >= 4


def test_split_is_by_chunk_group_not_by_question():
    groups = defaultdict(set)
    for _, c in _all_chunks():
        groups[sc.group_key(c)].add(sc.split_of(c))
    assert all(len(s) == 1 for s in groups.values())  # 같은 묶음은 한쪽에만
    # 하루 요약은 그날 구간 조각과 같은 쪽이다
    by_day = defaultdict(set)
    for _, c in _all_chunks():
        if c.kind != "place":
            by_day[(c.person_id, c.starts_at.date())].add(sc.split_of(c))
    assert all(len(s) == 1 for s in by_day.values())


def test_split_is_stable_and_has_both_sides():
    chunks = [c for _, c in _all_chunks()]
    first = [sc.split_of(c) for c in chunks]
    assert first == [sc.split_of(c) for c in chunks]  # 같은 입력이면 같은 분리
    final = sum(s == "final" for s in first) / len(first)
    assert 0.15 < final < 0.45  # 비율 0.3 근처
    assert sc.split_of(chunks[0], 0.3, "다른 시드") in ("dev", "final")


def _fake(responses):
    calls = []

    def complete(prompt, schema, system=None, max_tokens=None, model=None):
        calls.append(prompt)
        return SimpleNamespace(data=responses(len(calls) - 1, prompt))

    return complete, calls


def test_generate_counts_calls_by_formula_and_drops_bad_items():
    items = gq.plan({"span", "day"}, 0.3, "gabee-loc-1", 12)["dev"]
    per_chunk, batch = 2, 10  # 호출 한 번에 조각 5개

    def reply(n, prompt):
        return {
            "questions": [
                {"chunk": 0, "question": f"{n}번 호출의 첫 조각 질문 하나"},
                {"chunk": 0, "question": f"{n}번 호출의 첫 조각 질문 둘"},
                {"chunk": 0, "question": f"{n}번 호출의 첫 조각 질문 셋(초과분)"},
                {"chunk": 99, "question": "범위 밖 번호 질문입니다"},
                {"chunk": 1, "question": "짧"},
            ]
        }

    complete, calls = _fake(reply)
    questions, n = gq.generate(items, "dev", per_chunk, batch, complete)
    assert n == len(calls) == budget.question_gen_calls(len(items), per_chunk, batch)
    assert len(questions) == 2 * n  # 호출마다 첫 조각의 질문 2개만 남는다
    assert all(q["split"] == "dev" and q["gold"]["key"].count("|") == 4 for q in questions)
    assert len({q["id"] for q in questions}) == len(questions)


def test_dry_run_prints_estimate_and_real_run_needs_a_cap(capsys, tmp_path):
    assert gq.main(["--dry-run", "--out-dir", str(tmp_path), "--max-calls", "100000"]) == 0
    text = capsys.readouterr().out
    assert "호출 예상" in text and "dev:" in text and "final:" in text
    assert gq.main(["--out-dir", str(tmp_path)]) == 2  # 상한 없이는 실행하지 않는다
    with pytest.raises(SystemExit):
        gq.main(
            ["--dry-run", "--out-dir", str(tmp_path), "--max-calls", "1"]
        )  # 예상이 상한을 넘으면 멈춘다


def test_final_file_is_frozen(capsys, tmp_path):
    (tmp_path / "questions_final.json").write_text(json.dumps({"split": "final", "questions": []}))
    assert gq.main(["--dry-run", "--out-dir", str(tmp_path)]) == 0
    assert "얼려 둠" in capsys.readouterr().out
