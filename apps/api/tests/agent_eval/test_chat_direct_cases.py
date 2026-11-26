"""소통 Agent 단독 평가 사례 20건(`chat_direct_cases`)의 고정값·정합·근거·가짜 모델 시험(L0/L2, 실제 호출 없음).

직접 호출 경로(메인 미경유)가 이 사례에만 쓰이는지, 예산·보안 중단이 같은 규칙으로 도는지는 `test_chat_direct_gate.py` 가 본다.
"""

import pytest

from evals.agent_eval import case_files as cf
from evals.agent_eval import (
    chat_direct_cases,
    chat_direct_scripts,
    dev_cases,
    gen_cases,
    todo_routing_cases,
)
from evals.agent_eval.dev_cases import file_sha256
from evals.agent_eval.seeds import data as seed
from tests.agent_eval.runner_support import run

IDS = sorted(chat_direct_cases.IDS)
OFFICIAL_DEV_FILE_SHA = "c2d0bc8bcfcde47fc316bb4d080a002607152095bdca3ca28d54fd9e816e35a1"
FAMILY_TEXTS = [m.text for m in seed.MESSAGES if m.room == "family"]
FAMILY_TODOS = [t for t in seed.TODOS if t.creator in seed.FAMILY_USERS]
# 소통 Agent 가 정당하게 읽을 수 있는 근거: 가족 전체방 글과 가족 공동 할 일(제목·기한)
EVIDENCE = [*FAMILY_TEXTS, *(t.title for t in FAMILY_TODOS), *(t.due or "" for t in FAMILY_TODOS)]


@pytest.fixture(scope="module")
def items():
    return cf.load_cases(chat_direct_cases.PATH, "dev")


@pytest.fixture(scope="module")
def by_id(items):
    return {c.id: c for c in items}


# ---------- 고정값·정합 ----------
def test_the_cases_match_their_pins_and_are_frozen_before_any_model_output():
    assert chat_direct_cases.check_pins() == []
    pins = chat_direct_cases.build_pins("x")
    assert pins["frozen_before_any_model_output"] is True and pins["case_count"] == 20


def test_exactly_twenty_family_chat_dev_cases_with_empty_history_and_no_room_post(items):
    assert len(items) == 20 == len(chat_direct_cases.IDS)
    for c in items:
        assert c.id.startswith(chat_direct_cases.ID_PREFIX)
        assert c.split == "dev" and c.agent_path == "family_chat"
        assert c.setup.history == [] and c.setup.seed is None
        assert c.expect.outcome.posted_to_room is None and c.expect.outcome.can_answer is True
        assert c.expect.outcome.proposals == 0 and c.expect.security.forbidden_writes == []
        assert c.meta.synthetic is True
        assert c.meta.note.endswith(f"출처: {chat_direct_cases.SOURCES[c.id]}")
        assert all(call.stage == "family_chat" for call in c.expect.calls)


def test_every_area_is_covered_and_reuse_comes_first():
    areas = [chat_direct_cases.AREA_OF[i] for i in IDS]
    for area in chat_direct_cases.AREAS:
        assert areas.count(area) >= 2, area
    sources = list(chat_direct_cases.SOURCES.values())
    assert sum(s != "new" for s in sources) == 13 and sources.count("new") == 7


def test_reused_sources_exist_in_official_or_approved_synthetic_files():
    known = {c.id for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}
    known |= {spec[0] for spec in todo_routing_cases.SPECS}
    for case_id, source in chat_direct_cases.SOURCES.items():
        assert source == "new" or source in known, (case_id, source)


def test_the_ids_do_not_overlap_any_other_case_file(by_id):
    official = {c.id for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}
    gen = {c.id for c in cf.load_cases(gen_cases.GEN_PATH, "dev")}
    todo = {spec[0] for spec in todo_routing_cases.SPECS}
    assert not set(by_id) & (official | gen | todo)


def test_reused_security_lists_equal_the_official_cases(by_id):
    """공식 사례에서 옮긴 금지 문자열·부정 문구는 원본과 같다(옮기며 약하게 만들지 않았다)."""
    official = {c.id: c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}
    for case_id, source in chat_direct_cases.SOURCES.items():
        if source not in official or not official[source].expect.security.forbidden_strings:
            continue
        mine, theirs = by_id[case_id].expect, official[source].expect
        assert mine.security.forbidden_strings == theirs.security.forbidden_strings, case_id
        assert set(theirs.answer.not_contains) <= set(mine.answer.not_contains), case_id
        assert by_id[case_id].setup.as_user == official[source].setup.as_user
        assert by_id[case_id].setup.audience == official[source].setup.audience


def test_official_dev_and_other_approved_files_are_untouched():
    assert file_sha256(dev_cases.CASES_DEV_PATH.read_bytes()) == OFFICIAL_DEV_FILE_SHA
    assert gen_cases.check_pins() == [] and todo_routing_cases.check_pins() == []


def test_a_changed_case_row_breaks_the_pins(tmp_path):
    rows = chat_direct_cases.build()
    rows[0]["question"] += " "
    bad = tmp_path / "cases.json"
    bad.write_text(chat_direct_cases.render(rows), encoding="utf-8")
    problems = chat_direct_cases.check_pins(path=bad)
    assert any("해시" in p for p in problems) and any("정의" in p for p in problems)


def test_the_pins_file_is_never_overwritten(tmp_path):
    with pytest.raises(FileExistsError):
        chat_direct_cases.write(tmp_path / "a.json", chat_direct_cases.PINS_PATH)


# ---------- 시드 근거(LLM 심판 없음) ----------
def test_every_fact_needle_is_in_the_family_room_or_family_todos():
    for spec in chat_direct_cases.SPECS:
        for fact in spec["facts"]:
            assert any(fact in e for e in EVIDENCE), (spec["id"], fact)
        # 답 기준의 낱말은 사실(facts, 시드 근거)이거나 거절·없음 표현이다. 대안 묶음은 한쪽으로만 이뤄진다
        for word in spec["contains"]:
            assert word in spec["facts"] or word == "볼 수 없", (spec["id"], word)
        facts = {*spec["facts"], *(r for f in spec["facts"] for r in _date_renderings(f))}
        for group in spec["contains_any"]:
            kinds = {w in facts for w in group}
            assert len(kinds) == 1, (spec["id"], group)


def _date_renderings(fact: str) -> list[str]:
    """시드 날짜(YYYY-MM-DD)를 답에 쓰는 다른 표기(같은 사실)."""
    parts = fact.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return []
    month, day = int(parts[1]), int(parts[2])
    return [f"{month}월 {day}일", f"{month}/{day}"]


def test_search_arguments_hit_family_room_messages():
    for spec in chat_direct_cases.SPECS:
        for tool, args in spec["calls"]:
            for _arg, match, value in args:
                if tool == "search_messages" and match == "contains":
                    assert any(value in t for t in FAMILY_TEXTS), (spec["id"], value)


def test_no_result_topics_are_absent_from_everything_the_agent_can_read():
    for topic in ("강아지", "산책", "여행"):
        assert not any(topic in e for e in EVIDENCE), topic
    # 외식의 시각·장소는 지민의 일정에만 있고 가족방 글에는 없다(지어내면 안 된다)
    dinner = next(e for e in seed.EVENTS if e.title == "가족 외식")
    assert dinner.place == "한우식당" and dinner.start == "18:00"
    for value in ("한우식당", "18:00", "오후 6시", "저녁 6시"):
        assert not any(value in t for t in FAMILY_TEXTS), value
    assert any("토요일 저녁에 가족 외식" in t for t in FAMILY_TEXTS)


def test_today_has_no_due_family_todo_and_sujin_owns_only_the_milk():
    assert seed.REFERENCE_DAY == "2026-11-10"
    assert not [t for t in FAMILY_TODOS if t.due == seed.REFERENCE_DAY]
    assert [(t.title, t.due) for t in FAMILY_TODOS if t.assignee == "수진"] == [
        ("우유 사기", "2026-11-12")
    ]


def test_isolation_and_injection_targets_exist_in_the_seed():
    assert seed.CHAT_NOTICE_TEXT in FAMILY_TEXTS and seed.INJECTION_TEXT in FAMILY_TEXTS
    assert "삭제" in seed.INJECTION_TEXT
    assert not any("이웃" in t for t in FAMILY_TEXTS)  # 이웃 얘기는 다른 가족방에만 있다
    assert [m.room for m in seed.MESSAGES if "이웃" in m.text] == ["other"]
    assert not any("선물" in t for t in FAMILY_TEXTS)  # 선물 얘기는 1:1 방에만 있다


# ---------- 가짜 모델 L2(직접 호출) ----------
def test_every_case_has_exactly_one_script_without_a_main_line():
    assert set(chat_direct_scripts.SCRIPTS) == chat_direct_cases.IDS
    for script in chat_direct_scripts.SCRIPTS.values():
        assert "main" not in script and "family_chat" in script


def test_all_twenty_scripted_cases_pass_through_the_direct_path(items):
    report = run(items, scripts=chat_direct_scripts.SCRIPTS)
    assert len(report.records) == 20
    for rec in report.records:
        obs = report.observations[(rec.case_id, 0)]
        assert rec.status == "judged" and rec.passed is True, (rec, obs.answer)
        assert not rec.security_violations
        assert obs.calls and all(c.stage != "main" for c in obs.calls)
        assert obs.posted_to_room is None
    assert report.all_counted_passed


def test_a_wrong_tool_fails(by_id):
    (case_id,) = chat_direct_scripts.WRONG_TOOL
    report = run([by_id[case_id]], scripts=chat_direct_scripts.WRONG_TOOL)
    (rec,) = report.records
    assert rec.status == "judged" and rec.passed is False
    assert "missing_tool" in rec.failure_types
