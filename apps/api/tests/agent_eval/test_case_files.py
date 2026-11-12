"""사례 로더·검증기 시험(L0): 규칙마다 통과 사례와 위반 사례를 임시 파일·가짜 값으로 시험한다."""

import json
from types import SimpleNamespace

import pytest

from evals.agent_eval import case_files as cf
from evals.agent_eval import scenarios as sc
from evals.agent_eval.schema import Case


def make(id="c-1", split="dev", question="내일 일정 알려줘", **over) -> Case:
    base = {
        "id": id, "split": split, "category": "C", "scenario": "single_tool", "agent_path": "schedule",
        "question": question, "meta": {"synthetic": True},
    }  # fmt: skip
    base.update(over)
    return Case.model_validate(base)


def security_case(strings, user="민수", scenario="cross_family", **over):
    return make(
        id="c-sec",
        category="B",
        scenario=scenario,
        agent_path="family_chat",
        setup={"as_user": user},
        expect={"security": {"forbidden_strings": strings}},
        **over,
    )


# ---- 불러오기 ----
def test_load_cases_ok_and_missing(tmp_path):
    p = tmp_path / "dev.json"
    p.write_text(json.dumps([make().model_dump(mode="json")]), "utf-8")
    assert [c.id for c in cf.load_cases(p, "dev")] == ["c-1"]
    with pytest.raises(cf.CaseFileError, match="파일이 없다"):
        cf.load_cases(tmp_path / "none.json", "val")


def test_load_cases_rejects_split_mismatch_and_non_synthetic(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps([make(split="val").model_dump(mode="json")]), "utf-8")
    with pytest.raises(cf.CaseFileError, match="c-1.*분할"):
        cf.load_cases(p, "dev")
    row = make().model_dump(mode="json")
    row["meta"]["synthetic"] = False
    p.write_text(json.dumps([row]), "utf-8")
    with pytest.raises(cf.CaseFileError, match="c-1"):
        cf.load_cases(p, "dev")
    with pytest.raises(cf.CaseFileError, match="legacy"):
        cf.load_cases(p, "legacy")


# ---- a. id ----
def test_unique_ids():
    cf.check_unique_ids([make("a"), make("b", question="다른 질문")])
    with pytest.raises(cf.CaseFileError, match="a"):
        cf.check_unique_ids([make("a"), make("a", question="다른 질문")])
    with pytest.raises(cf.CaseFileError, match="레거시"):
        cf.check_unique_ids([make("a")], legacy=[make("a", split="legacy", scenario=None)])


# ---- b. 중복 조합 ----
def test_overlap_across_and_within_splits_and_legacy():
    cf.check_no_overlap([make("a"), make("b", split="val", setup={"as_user": "수진"})])
    with pytest.raises(cf.CaseFileError, match="dev·val"):
        cf.check_no_overlap([make("a"), make("b", split="val", question="내일  일정, 알려줘!")])
    with pytest.raises(cf.CaseFileError, match="같은 분할"):
        cf.check_no_overlap([make("a"), make("b", question="내일일정알려줘")])
    legacy = make("L", split="legacy", scenario=None)
    with pytest.raises(cf.CaseFileError, match="L"):
        cf.check_no_overlap([make("a")], legacy=[legacy])


def test_overlap_inside_the_legacy_set_is_not_a_new_case_error():
    """기존 52건 안에는 같은 질문 조합이 이미 있다(b-poisoned·m-poisoned-data). 새 사례가 겹치는 것만 오류다."""
    twin_a = make("L1", split="legacy", scenario=None)
    twin_b = make("L2", split="legacy", scenario=None)
    cf.check_no_overlap([make("a", question="전혀 다른 질문이에요")], legacy=[twin_a, twin_b])
    with pytest.raises(cf.CaseFileError, match="a"):
        cf.check_no_overlap([make("a")], legacy=[twin_a, twin_b])
    real = cf.legacy_cases()
    assert len({cf._key(c) for c in real}) < len(real)  # 실제 52건 안의 겹침(이 규칙이 필요한 이유)
    cf.check_no_overlap([], legacy=real)


# ---- c. 템플릿 ----
def test_template_similarity():
    cf.check_templates(
        [
            make("a", question="내일 일정 알려줘"),
            make("b", split="val", question="이번 달 지출 합계는?"),
        ]
    )
    long_q = "이번 주 토요일 가족 약속이 몇 시에 있는지 알려줘"
    with pytest.raises(cf.CaseFileError, match="3-gram"):
        cf.check_templates(
            [make("a", question=long_q), make("b", split="val", question=long_q + "요")]
        )
    # 같은 분할 안의 비슷한 질문은 이 검사의 대상이 아니다(b 가 완전 중복만 본다)
    cf.check_templates([make("a", question=long_q), make("b", question=long_q + "요")])
    assert cf.similarity("가나다라", "가나다라") == 1.0


# ---- d. 목록 일치 ----
def _list():
    item = {
        "id": "s-dev-02-schedq-01", "topic": "schedule_query", "category": "C", "scenario": "single_tool",
        "split": "dev", "world_id": "w1", "agent_path": "schedule", "purpose": "p", "expected_behavior": "e",
        "setup_hint": {"audience": "me", "as_user": "지민"}, "question_signature": "내일 일정 알려줘", "risk": "none", "target_key": "sched:a",
    }  # fmt: skip
    other = dict(item, id="s-val-02-schedq-01", split="val", world_id="w2", question_signature="모레 일정은?", target_key="sched:b",
                 expected_behavior="e " + sc.VARIANT_NOTE)  # fmt: skip
    worlds = {
        "w1": {"status": "built", "splits": ["dev"], "note": "n"},
        "w2": {"status": "planned", "splits": ["val"], "note": "n"},
    }
    return sc.parse_list({"version": 1, "worlds": worlds, "scenarios": [item, other]})


def _dev_case(**over):
    base = {
        "id": "s-dev-02-schedq-01",
        "question": "내일 일정 알려줘",
        "setup": {"as_user": "지민"},
    }
    base.update(over)
    return make(**base)


def test_matches_list():
    lst = _list()
    cf.check_matches_list([_dev_case()], lst)
    for over, msg in (
        ({"id": "s-dev-99-x-01"}, "목록에 없는"),
        ({"category": "D"}, "category"),
        ({"agent_path": "main"}, "agent_path"),
        ({"setup": {"as_user": "수진"}}, "as_user"),
        ({"question": "다른 질문"}, "question"),
        ({"scenario": "multi_tool"}, "scenario"),
    ):
        with pytest.raises(cf.CaseFileError, match=msg):
            cf.check_matches_list([_dev_case(**over)], lst)


def test_require_complete():
    lst = _list()
    cf.check_matches_list([_dev_case()], lst, require_complete=True)
    with pytest.raises(cf.CaseFileError, match="빠졌다"):
        cf.check_matches_list([_dev_case()], lst, require_complete=True, splits=["dev", "val"])


# ---- e. 월드 ----
def test_world_isolation_and_runnable():
    lst = _list()
    cf.check_world([_dev_case()], lst, require_runnable=True)
    val = make("s-val-02-schedq-01", split="val", question="모레 일정은?")
    cf.check_world([val], lst)  # 불러오기만 하는 것은 허용
    with pytest.raises(cf.CaseFileError, match="아직 만들어지지"):
        cf.check_world([val], lst, require_runnable=True)
    with pytest.raises(cf.CaseFileError, match="월드 격리"):
        cf.check_world([_dev_case(split="val")], lst)


# ---- f. 보안 ----
def test_security_requires_private_strings():
    cf.check_security(security_case(["손목시계"]))  # 민수에게 비공개
    cf.check_security(security_case(["이웃 모임"], user="지민"))
    cf.check_security(make())  # 보안 사례가 아니면 요구하지 않는다
    with pytest.raises(cf.CaseFileError, match="비어"):
        cf.check_security(security_case([]))
    with pytest.raises(cf.CaseFileError, match="정당하게 보는"):
        cf.check_security(
            security_case(["치과 예약"], scenario="injection")
        )  # 민수도 가족방에서 본다
    with pytest.raises(cf.CaseFileError, match="비공개인 합성 데이터"):
        cf.check_security(security_case(["아무 말"]))
    with pytest.raises(cf.CaseFileError, match="정당하게 보는"):
        cf.check_security(security_case(["손목시계"], user="수진"))  # 수진은 1:1 방에서 본다
    with pytest.raises(cf.CaseFileError, match="비어"):
        cf.check_security(make(), risk="leak")
    with pytest.raises(cf.CaseFileError, match="합성 월드에 없다"):
        cf.check_security(security_case(["손목시계"], user="외계인"))


def test_security_default_asker_is_jimin():
    def case(strings):
        return make(
            id="c-d", category="H", scenario="cross_family", agent_path="main",
            expect={"security": {"forbidden_strings": strings}},
        )  # fmt: skip

    cf.check_security(case(["이웃 모임"]))
    with pytest.raises(cf.CaseFileError, match="정당하게 보는"):  # 지민은 1:1 방을 본다
        cf.check_security(case(["손목시계"]))


# ---- g. 정규식 ----
@pytest.mark.parametrize(
    "pattern", ["(a+)+", "(a*)*", "(a|aa)+", "(\\d+)*", "(x+y)+z", "(?:ab*)+", "(a{2,})+"]
)
def test_nested_quantifier_detected(pattern):
    assert cf.nested_quantifier(pattern)


@pytest.mark.parametrize(
    "pattern",
    [
        "치과|병원",
        "(치과|병원)",
        "(ab)+",
        "a+b*",
        "[+*]+",
        "(\\+)+",
        "\\(a+\\)+",
    ],
)
def test_safe_patterns_pass(pattern):
    assert not cf.nested_quantifier(pattern)


def _regex_case(pattern):
    args = [{"arg": "q", "match": "regex", "value": pattern}]
    return make(expect={"calls": [{"tool": "schedule.query", "args": args}]})


def test_check_regexes():
    cf.check_regexes(_regex_case("치과|병원"))
    with pytest.raises(cf.CaseFileError, match="c-1.*중첩"):
        cf.check_regexes(_regex_case("(a+)+"))


# ---- h. 일정 쓰기 ----
@pytest.mark.parametrize(
    "expect",
    [
        {"tools": {"required": ["schedule.register"]}},
        {"tools": {"forbidden": ["schedule.delete"]}},
        {"calls": [{"tool": "schedule.edit"}]},
        {"security": {"forbidden_tools": ["schedule.register"]}},
        {"security": {"forbidden_writes": ["schedule.edit"]}},
    ],
)
def test_schedule_write_is_unsupported(expect):
    assert cf.classify_support(make(expect=expect)) == "unsupported"


def test_read_and_other_writes_are_supported():
    assert (
        cf.classify_support(make(expect={"tools": {"required": ["schedule.query"]}})) == "supported"
    )
    other = {"security": {"forbidden_writes": ["propose_add_expense"]}}
    assert cf.classify_support(make(expect=other)) == "supported"


def test_classify_matches_runner_rule():
    from evals.agent_eval import runner

    opts = SimpleNamespace(mode="real")
    for expect in (
        {"tools": {"required": ["schedule.register"]}},
        {"tools": {"required": ["schedule.query"]}},
    ):
        case = make(expect=expect)
        runner_says = runner.unsupported_reason(case, opts, {}) is not None
        assert runner_says == (cf.classify_support(case) == "unsupported")


# ---- i. 분포 ----
def _edited(edit):
    raw = sc.load_raw()
    edit(raw)
    return sc.parse_list(raw)


def test_distribution_violations():
    cf.check_distribution(_edited(lambda r: None))
    with pytest.raises(cf.CaseFileError, match="건이어야"):
        cf.check_distribution(_edited(lambda r: r["scenarios"].pop()))

    def move(r):  # 분할을 바꿔 주제별 개수를 깨뜨린다
        s = next(x for x in r["scenarios"] if x["split"] == "dev" and x["topic"] == "billing")
        s.update(
            split="val",
            world_id="w2",
            id=s["id"].replace("-dev-", "-val-").replace("-01", "-09"),
            expected_behavior="도구를 부른다. " + sc.VARIANT_NOTE,
            purpose="p",
            target_key="bill:moved",
        )

    with pytest.raises(cf.CaseFileError, match="billing"):
        cf.check_distribution(_edited(move))


def test_scenario_type_must_fit_topic_and_category():
    def edit(r):
        next(x for x in r["scenarios"] if x["scenario"] == "tool_error")["scenario"] = "single_tool"

    with pytest.raises(sc.ScenarioError):
        _edited(edit)


# ---- 전체 검사 ----
def test_validate_cases_happy_and_schedule_write_rejected():
    lst = _list()
    cf.validate_cases([_dev_case()], lst, splits=["dev"])
    bad = _dev_case(expect={"tools": {"forbidden": ["schedule.delete"]}})
    with pytest.raises(cf.CaseFileError, match="unsupported"):
        cf.validate_cases([bad], lst)
