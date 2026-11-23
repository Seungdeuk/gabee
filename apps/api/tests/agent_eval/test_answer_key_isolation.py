"""정답지 유입 방지 회귀 시험(WP5, L0 규칙: 가짜 모델·임시 SQLite·네트워크 차단, 실제 호출 0회).

사례의 `expect`(정답지: 필수 문구·금지 문구·금지 문자열·기대 도구·기대 호출 인자·메모)를 고유 표식 문자열로 바꾼 사본을 가짜 모드로 실행하고,
가짜 모델이 받은 **모든 요청 본문**(`FakeModel.record_bodies`: 메인·정산·소통·일정 하위 Agent 요청의 시스템 프롬프트·메시지·도구 정의·구조화 출력 설정)에 표식이 없음을 확인한다.
실행기는 모델 요청을 사례의 `question`·`setup`(질문자·방·대화 이력)으로만 만들고 `expect` 는 채점·보안 판정에서만 읽는다. 이 시험은 그것을 값으로 고정한다.

시험이 공허하지 않도록 대조군을 둔다: 같은 방식으로 질문(`question`)·이전 대화(`setup.history`)에 넣은 표식은 본문에 나타난다(탐지가 실제로 작동한다는 증거).
개발셋(dev)에도 같은 시험을 걸어 기존 동작을 고정한다(dev 사례 파일·대본은 바뀌지 않는다).
"""

import json
import re
from typing import Any

import pytest

from app.shared.llm import transport
from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases, dev_scripts, fake_model, val_cases
from evals.agent_eval.schema import Case
from tests.agent_eval.runner_support import run

MARK = "ZZKEY"  # 표식 접두어: 실제 어떤 글에도 나올 수 없는 낱말


@pytest.fixture(scope="module")
def tripwire():
    called: list[tuple] = []
    real = transport.post_messages

    def boom(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("실제 모델 전송 함수가 불렸다")

    transport.post_messages = boom
    try:
        yield called
    finally:
        transport.post_messages = real


def marker(case_id: str, kind: str, i: int = 0) -> str:
    return f"{MARK}-{kind}{i}-{case_id.removeprefix('s-')}"


def with_markers(case: Case) -> tuple[Case, set[str]]:
    """정답지(`expect`)와 메모의 모든 값을 고유 표식으로 바꾼 사본과 표식 집합. 질문·setup 은 그대로다(모델 요청의 원천이다)."""
    row: dict[str, Any] = case.model_dump(mode="json")
    exp = row["expect"]
    marks: set[str] = set()

    def m(kind: str, i: int = 0) -> str:
        value = marker(case.id, kind, i)
        marks.add(value)
        return value

    exp["tools"] = {
        "required": [m("req", i) for i, _ in enumerate(exp["tools"]["required"])],
        "forbidden": [m("forb", i) for i, _ in enumerate(exp["tools"]["forbidden"])],
        "allowed": [],
    }
    for i, call in enumerate(exp["calls"]):
        call["tool"] = m("calltool", i)
        for j, arg in enumerate(call["args"]):
            arg["arg"] = m("argname", i * 10 + j)
            arg["match"] = "eq"
            arg["value"] = m("argvalue", i * 10 + j)
    ans = exp["answer"]
    ans["contains"] = [m("has", i) for i, _ in enumerate(ans["contains"])]
    ans["contains_any"] = [
        [m("any", i * 10 + 0), m("any", i * 10 + 1)]
        for i, _ in enumerate(ans.get("contains_any", []))
    ]
    ans["not_contains"] = [m("not", i) for i, _ in enumerate(ans["not_contains"])]
    sec = exp["security"]
    sec["forbidden_strings"] = [m("secret", i) for i, _ in enumerate(sec["forbidden_strings"])]
    sec["forbidden_tools"] = [m("sectool", i) for i, _ in enumerate(sec["forbidden_tools"])]
    sec["forbidden_writes"] = [m("secwrite", i) for i, _ in enumerate(sec["forbidden_writes"])]
    row["meta"]["note"] = m("note")
    marked = Case.model_validate(row)
    return marked, marks


def bodies_of(report) -> dict[str, list[str]]:
    """사례 id -> 그 사례 실행에서 가짜 모델이 받은 모든 요청 본문(JSON 글)."""
    out: dict[str, list[str]] = {}
    for (case_id, _), fake in report.fakes.items():
        out.setdefault(case_id, []).extend(
            json.dumps(b, ensure_ascii=False, sort_keys=True) for b in fake.bodies
        )
    return out


def run_with_bodies(cases: list[Case], scripts, **opts):
    fake_model.FakeModel.record_bodies = True
    try:
        return run(cases, None, scripts=scripts, **opts)
    finally:
        fake_model.FakeModel.record_bodies = False


@pytest.fixture(scope="module")
def val_marked(tripwire):
    cases = cf.load_cases(val_cases.CASES_VAL_PATH, "val")
    pairs = [with_markers(c) for c in cases]
    report = run_with_bodies(
        [c for c, _ in pairs], dev_scripts.scripts_for("val"), purpose="baseline"
    )
    return report, pairs


@pytest.fixture(scope="module")
def dev_marked(tripwire):
    cases = cf.load_cases(dev_cases.CASES_DEV_PATH, "dev")
    pairs = [with_markers(c) for c in cases]
    report = run_with_bodies([c for c, _ in pairs], dev_scripts.scripts_for("dev"))
    return report, pairs


def check_no_marker_in_any_request(report, pairs, expected_cases: int):
    bodies = bodies_of(report)
    assert len(pairs) == expected_cases
    all_marks: set[str] = set()
    total = 0
    for case, marks in pairs:
        texts = bodies.get(case.id, [])
        assert texts, f"{case.id}: 가로챈 요청 본문이 없다(시험이 공허하다)"
        total += len(texts)
        all_marks |= marks
        blob = "\n".join(texts)
        leaked = sorted(mark for mark in marks if mark in blob)
        assert not leaked, (case.id, leaked)
    # 표식 접두어 자체가 어느 본문에도 없다(어느 사례의 표식이든 다른 사례 요청에 섞이지 않았다)
    assert all(MARK not in text for texts in bodies.values() for text in texts)
    assert total >= expected_cases and len(all_marks) > expected_cases  # 사례마다 여러 표식이 있다


def test_no_answer_key_marker_reaches_any_model_request_for_the_val_cases(val_marked, tripwire):
    report, pairs = val_marked
    # 표식 사본은 정답지를 잃어 실패해도 된다: 모든 사례가 끝까지 돌아 요청이 만들어졌는지만 본다
    assert {r.status for r in report.records} <= {"judged", "missing_observation"}
    assert all(r.status == "judged" for r in report.records)
    check_no_marker_in_any_request(report, pairs, 18)
    assert tripwire == []


def test_no_answer_key_marker_reaches_any_model_request_for_the_dev_cases(dev_marked, tripwire):
    report, pairs = dev_marked
    assert all(r.status == "judged" for r in report.records)
    check_no_marker_in_any_request(report, pairs, 36)
    assert tripwire == []


def test_the_bodies_cover_every_agent_request_including_sub_agents_and_tool_definitions(val_marked):
    """가로챈 요청에 메인·정산·소통·일정(구조화 출력) 요청이 모두 들어 있고, 도구 정의·시스템 프롬프트·메시지가 있다(공허하지 않다)."""
    report, _ = val_marked
    agents: set[str] = set()
    for fake in report.fakes.values():
        agents |= set(fake.agents)
        assert len(fake.bodies) == fake.calls == len(fake.agents)
        for body in fake.bodies:
            assert body.get("system") and body.get("messages") and "model" in body
    assert agents == {"main", "billing", "family_chat", "schedule"}
    assert any("tools" in b for f in report.fakes.values() for b in f.bodies)
    assert any("output_config" in b for f in report.fakes.values() for b in f.bodies)


def test_control_a_marker_in_the_question_or_the_history_does_reach_the_request(tripwire):
    """대조군: 질문·이전 대화에 넣은 표식은 본문에 나타난다. 위 시험의 '표식 없음'이 탐지 실패가 아니라는 증거다."""
    base = {c.id: c for c in cf.load_cases(val_cases.CASES_VAL_PATH, "val")}
    q = base["s-val-06-docs-01"].model_copy(
        update={"question": f"{MARK}-Q 건강검진 안내문 공복 시간"}
    )
    h_row = base["s-val-01-routing-02"].model_dump(mode="json")
    h_row["setup"]["history"] = [{"role": "user", "text": f"{MARK}-H 이전 대화"}]
    history = Case.model_validate(h_row)
    report = run_with_bodies([q, history], dev_scripts.scripts_for("val"), purpose="baseline")
    bodies = bodies_of(report)
    assert any(f"{MARK}-Q" in t for t in bodies[q.id])
    assert any(f"{MARK}-H" in t for t in bodies[history.id])


def test_control_the_marker_swap_changes_only_the_expect_not_the_request(tripwire):
    """표식 사본과 원본 사례는 같은 질문·setup 이라 같은 요청 본문을 만든다(정답지만 바뀌었다)."""
    original = cf.load_cases(val_cases.CASES_VAL_PATH, "val")[10:12]  # docs-01·docs-02
    swapped = [with_markers(c)[0] for c in original]
    for a, b in zip(original, swapped, strict=True):
        assert (a.id, a.question, a.setup, a.agent_path) == (
            b.id,
            b.question,
            b.setup,
            b.agent_path,
        )
        assert a.expect != b.expect
    first = run_with_bodies(original, dev_scripts.scripts_for("val"), purpose="baseline")
    second = run_with_bodies(swapped, dev_scripts.scripts_for("val"), purpose="baseline")

    # 도구 결과의 기록 id(무작위 16진수)는 월드를 다시 만들 때마다 달라서 같은 글자로 바꿔 비교한다
    def normalized(report):
        return {
            case_id: [re.sub(r"[0-9a-f]{12,}", "ID", text) for text in texts]
            for case_id, texts in bodies_of(report).items()
        }

    assert normalized(first) == normalized(second)
