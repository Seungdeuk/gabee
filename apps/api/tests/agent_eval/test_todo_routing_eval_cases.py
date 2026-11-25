"""할 일 라우팅 회귀 평가 사례 2건(`todo_routing_cases`)의 고정값·정합·가짜 모델 시험(L0/L2, 실제 호출 없음).

이 파일은 사례의 설계·고정값·가짜 모델 시험이다. 실호출 게이트가 이 두 사례만 정확히 허용하는지(그리고 그 밖은 계속 거부하는지)는 `test_todo_gate.py` 가 본다.
공식 dev·일반화 사례 파일과 그 고정값은 그대로여야 한다.
"""

import pytest

from app.features.ai_assistant import agents
from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases, gen_cases, todo_routing_cases, todo_routing_scripts
from evals.agent_eval.dev_cases import file_sha256
from tests.agent_eval.runner_support import run

FAMILY, TAB = todo_routing_cases.FAMILY_ID, todo_routing_cases.TAB_ID
OFFICIAL_DEV_FILE_SHA = "c2d0bc8bcfcde47fc316bb4d080a002607152095bdca3ca28d54fd9e816e35a1"


@pytest.fixture(scope="module")
def items():
    return cf.load_cases(todo_routing_cases.PATH, "dev")


@pytest.fixture(scope="module")
def by_id(items):
    return {c.id: c for c in items}


def _windows(text: str, size: int = 10) -> set[str]:
    return {text[i : i + size] for i in range(max(1, len(text) - size + 1))}


# ---------- 고정값·정합 ----------
def test_the_cases_match_their_pins_and_are_frozen_before_any_model_output():
    assert todo_routing_cases.check_pins() == []
    pins = todo_routing_cases.build_pins("x")
    assert pins["frozen_before_any_model_output"] is True and pins["case_count"] == 2


def test_the_two_cases_encode_the_agreed_routing_policy(by_id):
    family, tab = by_id[FAMILY].expect, by_id[TAB].expect
    assert (family.tools.required, family.tools.forbidden) == (
        ["ask_family_chat"],
        ["ask_schedule", "ask_billing"],
    )
    assert (tab.tools.required, tab.tools.forbidden) == (
        ["ask_schedule"],
        ["ask_family_chat", "ask_billing"],
    )
    for c in by_id.values():
        assert c.agent_path == "main" and c.split == "dev" and c.expect.outcome.proposals == 0
        assert c.expect.security.forbidden_writes == []  # 쓰기 게이트가 신규 사례에 그대로 적용된다


def test_the_cases_are_read_only_synthetic_and_check_other_family_strings(by_id):
    for c in by_id.values():
        assert c.meta.synthetic is True
        assert tuple(c.expect.security.forbidden_strings) == gen_cases.FORBIDDEN_STRINGS
        assert {"ask_family_chat", "ask_schedule", "ask_billing"} <= set(
            c.expect.security.check_args_of
        )


def test_the_questions_are_not_copied_from_official_cases_or_the_prompt(by_id):
    """공식 dev·일반화 질문과 프롬프트 지침(`PROMPT_NOTE`)의 문장을 복사하지 않았다(10글자 창이 겹치지 않는다)."""
    official = [c.question for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")]
    gen = [c.question for c in cf.load_cases(gen_cases.GEN_PATH, "dev")]
    note = agents.PROMPT_NOTE
    for c in by_id.values():
        for other in (*official, *gen):
            assert c.question != other
            assert not (_windows(c.question) & _windows(other)), (c.id, other)
        assert not any(w in note for w in _windows(c.question)), c.id


def test_the_ids_do_not_overlap_the_official_dev_or_generalization_ids(by_id):
    official = {c.id for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")}
    gen = {c.id for c in cf.load_cases(gen_cases.GEN_PATH, "dev")}
    assert not (set(by_id) & official) and not (set(by_id) & gen)


def test_official_dev_and_generalization_files_and_pins_are_untouched():
    assert file_sha256(dev_cases.CASES_DEV_PATH.read_bytes()) == OFFICIAL_DEV_FILE_SHA
    assert gen_cases.check_pins() == []


def test_a_changed_case_row_breaks_the_pins(tmp_path):
    rows = todo_routing_cases.build()
    rows[0]["question"] += " "
    bad = tmp_path / "cases.json"
    bad.write_text(todo_routing_cases.render(rows), encoding="utf-8")
    problems = todo_routing_cases.check_pins(path=bad)
    assert any("해시" in p for p in problems) and any("정의" in p for p in problems)


def test_the_pins_file_is_never_overwritten(tmp_path):
    with pytest.raises(FileExistsError):
        todo_routing_cases.write(tmp_path / "a.json", todo_routing_cases.PINS_PATH)


# ---------- 가짜 모델 L2 ----------
@pytest.mark.parametrize("case_id", [FAMILY, TAB])
def test_the_policy_script_passes_and_calls_only_the_named_agent(by_id, case_id):
    report = run([by_id[case_id]], scripts=todo_routing_scripts.SCRIPTS)
    (rec,) = report.records
    obs = report.observations[(case_id, 0)]
    assert rec.status == "judged" and rec.passed is True, rec
    called = sorted({c.name for c in obs.calls if c.stage == "main"})
    assert called == by_id[case_id].expect.tools.required
    assert not any(c.name.startswith(todo_routing_cases.WRITE_PREFIXES) for c in obs.calls)
    assert not rec.security_violations


@pytest.mark.parametrize("case_id", [FAMILY, TAB])
def test_asking_the_other_list_s_agent_too_is_a_double_lookup_failure(by_id, case_id):
    report = run([by_id[case_id]], scripts=todo_routing_cases_scripts_violating(case_id))
    (rec,) = report.records
    assert rec.passed is not True and "wrong_tool" in rec.failure_types


def todo_routing_cases_scripts_violating(case_id):
    return {case_id: todo_routing_scripts.VIOLATING[case_id]}
