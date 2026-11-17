"""개발셋 36건 사례 본문(`data/cases_dev.json`)의 시험(L0). 사례 파일·대본·확정 목록만 읽고 모델·DB·네트워크는 쓰지 않는다.

사례 파일은 `dev_cases.build()` 가 확정 목록에서 만든다: 손으로 고친 파일을 막고, 목록과 어긋나지 않았는지 `case_files.validate_cases`(규칙 a~i 전부)로 본다.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases, dev_scripts
from evals.agent_eval import scenarios as sc
from evals.agent_eval.schema import Case
from evals.agent_eval.seeds import data as seed_data
from evals.agent_eval.write_tools import WRITE_TOOLS

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def lst():
    return sc.load_scenarios()


@pytest.fixture(scope="module")
def cases():
    return cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")


def dev_items(lst):
    return [s for s in lst.scenarios if s.split == "dev"]


def test_the_case_file_is_exactly_what_the_builder_makes_from_the_locked_list():
    assert dev_cases.CASES_DEV_PATH.read_text("utf-8") == dev_cases.render(dev_cases.build())


def test_36_cases_in_the_order_of_the_locked_list_and_in_cli_dev_file_format(lst, cases):
    assert [c.id for c in cases] == [s.id for s in dev_items(lst)] and len(cases) == 36
    rows = json.loads(dev_cases.CASES_DEV_PATH.read_text("utf-8"))
    assert [Case.model_validate(r).id for r in rows] == [
        c.id for c in cases
    ]  # cli._read_cases 와 같다
    assert all(c.meta.synthetic and c.split == "dev" for c in cases)


def test_all_validation_rules_pass_with_the_legacy_cases_and_a_runnable_world(lst, cases):
    """규칙 a~i: id 유일(레거시 포함)·중복 없음·템플릿·목록 일치·월드(runnable)·보안·정규식·일정 쓰기 분류·분포."""
    cf.validate_cases(cases, lst, cf.legacy_cases(), require_complete=True, require_runnable=True)
    cf.check_distribution(lst)
    assert {cf.classify_support(c) for c in cases} == {
        "supported"
    }  # 개발 36건은 모두 실행 대상이다
    assert all(s.world_id == "w1" and not s.needs for s in dev_items(lst))


def test_no_case_names_a_schedule_write_tool(cases):
    banned = WRITE_TOOLS["schedule"]
    assert not [c.id for c in cases if cf.named_tools(c) & banned]


def test_security_strings_come_from_the_seed_and_cover_the_listed_targets(lst, cases):
    """누출 사례의 금지 문자열은 질문자별 비공개 값(`seeds.data.forbidden_strings`) 그대로다(손으로 쓴 문자열 없음)."""
    by_id = {s.id: s for s in lst.scenarios}
    checked = 0
    for c in cases:
        item = by_id[c.id]
        strings = c.expect.security.forbidden_strings
        user = c.setup.as_user or seed_data.FAMILY_USERS[0]
        if item.risk in {"leak", "injection"} or item.topic == "doc_search":
            # 사례 파일은 시드 개정 1 의 값이 정답지다. 개정 2 의 일정 비공개 전용 식별값은 공통 보안 조건이 모든 사례에 붙여 검사한다
            # (`test_scope_leak_private_ids.py`). 그래서 사례 단위 목록은 그 식별값을 뺀 값과 같고, 전체 목록의 부분집합이다
            assert strings == seed_data.forbidden_strings(user, include_private_ids=False), c.id
            assert set(strings) <= set(seed_data.forbidden_strings(user)), c.id
            checked += 1
        else:
            assert not strings, c.id
        assert set(item.private_targets) <= set(strings), c.id
    assert checked == 8 + 3
    docs = next(c for c in cases if c.id == "s-dev-06-docs-01")
    assert (
        "이웃가족 냉장고 보증서" in docs.expect.security.forbidden_strings
    )  # 권한 없는 문서(다른 가족)


def test_write_risk_cases_forbid_write_tools_by_name(lst, cases):
    allowed_writes = {t for names in WRITE_TOOLS.values() for t in names}
    for c in cases:
        if next(s for s in lst.scenarios if s.id == c.id).risk == "write":
            names = set(c.expect.security.forbidden_writes) | set(c.expect.security.forbidden_tools)
            assert names and names <= allowed_writes, c.id


def test_every_case_has_one_normal_script_and_security_cases_have_violating_ones(lst, cases):
    assert set(dev_scripts.SCRIPTS) == {c.id for c in cases}
    assert set(dev_scripts.scripts_for("dev")) == set(dev_scripts.SCRIPTS)
    assert dev_scripts.scripts_for("val") == {}  # 개발셋 대본만 CLI 에 넘긴다
    assert set(dev_scripts.VIOLATING) <= set(dev_scripts.SCRIPTS)
    security = {
        s.id
        for s in dev_items(lst)
        if s.topic in {"private_1to1", "group_isolation", "injection"}
        or s.risk in {"leak", "write", "injection"}
    }
    assert len(security) == 12
    assert security <= set(dev_scripts.VIOLATING)
    for variants in dev_scripts.VIOLATING.values():
        assert variants
        for v in variants.values():
            assert v.failure in {"wrong_tool", "unapproved_write", "scope_leak"} and v.label


def test_violating_scripts_are_not_the_cli_default(cases):
    for variants in dev_scripts.VIOLATING.values():
        for v in variants.values():
            assert all(v.script is not s for s in dev_scripts.SCRIPTS.values())


# ---- 공식 D 범주 30건의 세부 유형별 분포 ----
D_TOPICS = ("main_routing", "billing", "care", "doc_search", "compound")
# {주제: {유형: (dev, val, test)}}: `docs/features/agent-eval.md` E5b 소절의 표와 같다. 틀리면 문서를 이 계산값에 맞춘다.
D_TABLE = {
    "main_routing": {"single_tool": (2, 1, 1), "no_tool": (1, 1, 0)},
    "billing": {"single_tool": (2, 1, 1), "multi_tool": (1, 1, 0)},
    "care": {"no_tool": (3, 2, 1)},
    "doc_search": {"single_tool": (3, 2, 1)},
    "compound": {"multi_tool": (3, 1, 2)},
}


def d_table(lst):
    counts = Counter((s.topic, s.scenario, s.split) for s in lst.scenarios if s.category == "D")
    out: dict[str, dict[str, tuple[int, int, int]]] = {}
    for (topic, kind, _), _n in sorted(counts.items()):
        out.setdefault(topic, {})[kind] = tuple(
            counts[(topic, kind, sp)] for sp in sc.LISTED_SPLITS
        )
    return out


def test_the_d_category_distribution_matches_the_documented_table(lst):
    d = [s for s in lst.scenarios if s.category == "D"]
    assert len(d) == 30 and {s.topic for s in d} == set(D_TOPICS)
    assert Counter(s.topic for s in d) == dict.fromkeys(D_TOPICS, 6)  # 주제마다 6건
    assert d_table(lst) == D_TABLE
    assert sum(sum(v) for kinds in D_TABLE.values() for v in kinds.values()) == 30
    assert tuple(
        sum(v[i] for kinds in D_TABLE.values() for v in kinds.values()) for i in range(3)
    ) == (15, 9, 6)


def test_the_documented_markdown_table_equals_the_computed_one(lst):
    """문서 숫자가 틀리면 시험이 아니라 문서를 계산값에 맞춘다."""
    doc = (REPO_ROOT / "docs" / "features" / "agent-eval.md").read_text("utf-8")
    kinds = ("single_tool", "multi_tool", "no_tool")

    def cell(counts):
        return "/".join(map(str, counts)) if counts else "-"

    for topic in D_TOPICS:
        row = D_TABLE[topic]
        total = tuple(sum(v[i] for v in row.values()) for i in range(3))
        cells = [cell(row.get(k)) for k in kinds] + [cell(total)]
        assert f"| {topic} | " + " | ".join(cells) + " |" in doc, topic
    totals = [
        tuple(sum(r[k][i] for r in D_TABLE.values() if k in r) for i in range(3)) for k in kinds
    ]
    grand = tuple(sum(t[i] for t in totals) for i in range(3))
    assert "| 합계 | " + " | ".join([cell(t) for t in totals] + [cell(grand)]) + " |" in doc
