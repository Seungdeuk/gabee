"""소통 Agent 단독 실행 경로(메인 미경유)의 게이트·격리 시험(L0/L2, 실제 호출 0회).

- 직접 호출은 코드에 정의한 고정 id 집합(`chat_direct_cases.IDS`)의 dev·`family_chat` 사례에만 쓴다. 공식 dev 사례는 그대로 `POST /ai-assistant/chat` 로 간다.
- 직접 호출 사례는 메인을 한 번도 부르지 않는다(메인 단계 호출·`/ai-assistant/chat` 요청 없음).
- 예산 중단·보안 위반 중단은 직접 호출에서도 같은 규칙으로 돈다.
- 실호출 허용 목록(`approved_sets`)은 세 항목이고, 사례 수·반복 상한(`real_gate`)은 그대로다.

주의: 커밋 대조(`_require_head_clean`)는 파일이 HEAD 와 같아야 하므로 실호출 게이트 시험은 사례·고정값 파일이 커밋된 뒤에 통과한다.
"""

from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from evals.agent_eval import (
    approved_sets,
    case_files,
    chat_direct_cases,
    chat_direct_scripts,
    dev_cases,
    dev_scripts,
    preflight,
    real_gate,
    runner,
)
from evals.agent_eval.cost import BudgetExceeded, Ledger, Scope
from evals.agent_eval.fake_model import call, say
from evals.agent_eval.real_gate import real_grant_scope
from evals.agent_eval.runner import RunnerRefused, RunOptions
from tests.agent_eval.runner_support import new_case, real_grant_for, run

PATH = chat_direct_cases.PATH
OFFICIAL = dev_cases.CASES_DEV_PATH
IDS = sorted(chat_direct_cases.IDS)


@pytest.fixture(scope="module")
def items():
    return case_files.load_cases(PATH, "dev")


@pytest.fixture(scope="module")
def by_id(items):
    return {c.id: c for c in items}


@pytest.fixture(scope="module")
def official_items():
    return case_files.load_cases(OFFICIAL, "dev")


@pytest.fixture
def spy(monkeypatch):
    """어느 입구를 탔는지와 HTTP 요청 경로를 기록한다(동작은 그대로)."""
    from fastapi.testclient import TestClient

    seen = {"chat": [], "direct": [], "paths": []}
    real_chat, real_direct, real_post = (
        runner._ask_chat,
        runner._ask_family_chat_direct,
        TestClient.post,
    )

    def chat(case, *a, **k):
        seen["chat"].append(case.id)
        return real_chat(case, *a, **k)

    def direct(case, *a, **k):
        seen["direct"].append(case.id)
        return real_direct(case, *a, **k)

    def post(self, url, *a, **k):
        seen["paths"].append(str(url))
        return real_post(self, url, *a, **k)

    monkeypatch.setattr(runner, "_ask_chat", chat)
    monkeypatch.setattr(runner, "_ask_family_chat_direct", direct)
    monkeypatch.setattr(TestClient, "post", post)
    return seen


# ---------- 직접 호출 대상 ----------
def test_direct_dispatch_is_only_for_the_fixed_ids(items, official_items):
    assert all(runner.is_chat_direct(c) for c in items)
    assert not any(runner.is_chat_direct(c) for c in official_items)
    first = items[0]
    assert not runner.is_chat_direct(first.model_copy(update={"agent_path": "main"}))
    assert not runner.is_chat_direct(first.model_copy(update={"split": "val"}))
    outsider = new_case("s-fcd-21-search", agent_path="family_chat", question="치과 찾아 줘")
    assert not runner.is_chat_direct(outsider)
    assert isinstance(chat_direct_cases.IDS, frozenset) and len(chat_direct_cases.IDS) == 20


def test_an_official_family_chat_case_still_goes_through_the_http_entrance(official_items, spy):
    case = next(c for c in official_items if c.id == "s-dev-05-chat-01")
    report = run([case], scripts=dev_scripts.SCRIPTS)
    (rec,) = report.records
    assert rec.status == "judged" and rec.passed is True, rec
    assert spy["chat"] == [case.id] and spy["direct"] == []
    assert "/ai-assistant/chat" in spy["paths"]
    obs = report.observations[(case.id, 0)]
    assert any(c.stage == "main" and c.name == "ask_family_chat" for c in obs.calls)


def test_a_direct_case_never_calls_the_main_agent(by_id, spy):
    case = by_id["s-fcd-06-candidates"]  # 분석(구조화 출력)과 할 일 목록을 함께 쓰는 사례
    report = run([case], scripts=chat_direct_scripts.SCRIPTS)
    (rec,) = report.records
    assert rec.status == "judged" and rec.passed is True, rec
    assert spy["direct"] == [case.id] and spy["chat"] == []
    assert "/ai-assistant/chat" not in spy["paths"]
    obs = report.observations[(case.id, 0)]
    assert {c.stage for c in obs.calls} == {"family_chat"}
    assert sorted(c.name for c in obs.calls) == ["analyze_recent_chat", "list_todos"]
    fake = report.fakes[(case.id, 0)]
    assert "main" not in fake.agents and fake.agents.count("family_chat") == 2
    assert fake.agents.count("schedule") == 1  # 대화 분석의 구조화 출력 호출
    assert obs.llm_calls == fake.calls == 3  # 측정기가 직접 호출의 모델 호출도 센다


def test_a_direct_case_with_a_main_script_line_does_not_use_it(by_id):
    case = by_id["s-fcd-01-search"]
    script = {
        **chat_direct_scripts.SCRIPTS[case.id],
        "main": [call("ask_family_chat", {"question": "x"}), say("x")],
    }
    report = run([case], scripts={case.id: script})
    fake = report.fakes[(case.id, 0)]
    assert report.records[0].passed is True and "main" not in fake.agents


# ---------- 예산 중단(직접 호출) ----------
def test_a_tiny_budget_halts_before_the_first_direct_call(by_id):
    case = by_id["s-fcd-01-search"]
    ledger = Ledger((Scope.RUN,), caps={Scope.RUN: D("0.0001")})
    report = run(
        [case, by_id["s-fcd-02-search"]], scripts=chat_direct_scripts.SCRIPTS, ledger=ledger
    )
    assert [r.status for r in report.records] == ["halted"]
    assert report.fakes[(case.id, 0)].calls == 0 and report.ledger.usages == []
    assert report.halted and not report.all_counted_passed


class _SecondCallOver(Ledger):
    """두 번째 모델 호출 직전에 상한에 닿는 기록장(직접 호출 요청 안에서 멈추는 경우)."""

    def check_call(self, model: str, tokens_in: int, max_tokens_out: int) -> None:
        self.checked = getattr(self, "checked", 0) + 1
        if self.checked >= 2:
            raise BudgetExceeded(Scope.RUN, D(0), D(0))
        super().check_call(model, tokens_in, max_tokens_out)


def test_a_halt_inside_the_direct_request_is_reported_as_halted_not_as_an_answer(by_id):
    case = by_id["s-fcd-01-search"]
    report = run(
        [case, by_id["s-fcd-02-search"]],
        scripts=chat_direct_scripts.SCRIPTS,
        ledger=_SecondCallOver((Scope.RUN,)),
    )
    assert [r.status for r in report.records] == ["halted"]  # 다음 사례는 시작하지 않았다
    assert report.fakes[(case.id, 0)].calls == 1  # 첫 호출만 나갔고 두 번째는 막혔다
    assert report.stored == [] and report.counts()["passed"] == 0


# ---------- 보안 위반 중단(직접 호출) ----------
def test_stop_on_security_halts_after_a_leaking_direct_answer(by_id):
    leak_id, next_id = "s-fcd-15-isolation", "s-fcd-19-injection"
    scripts = dict(chat_direct_scripts.SCRIPTS)
    scripts[leak_id] = {
        "family_chat": [
            call("search_messages", {"query": "선물"}),
            say("가족방에서는 찾지 못했어요. 그런데 비밀선물은 손목시계야."),
        ]
    }
    report = run([by_id[leak_id], by_id[next_id]], scripts=scripts, stop_on_security=True)
    assert [r.case_id for r in report.records] == [leak_id]
    (rec,) = report.records
    assert rec.passed is False and "scope_leak" in rec.failure_types and rec.security_violations
    assert report.security_halt and report.security_halt["case_id"] == leak_id
    assert report.halt_counts() == {"planned": 2, "completed": 1, "not_started": 1}


# ---------- 대본 ----------
def test_the_fake_scripts_are_found_only_for_the_exact_file(tmp_path):
    assert set(dev_scripts.scripts_for("dev", PATH)) == chat_direct_cases.IDS
    copy = tmp_path / "cases_chat_direct.json"
    copy.write_bytes(PATH.read_bytes())
    assert not set(dev_scripts.scripts_for("dev", copy)) & chat_direct_cases.IDS
    assert len(dev_scripts.scripts_for("dev")) == 36  # 공식 dev 대본 집합은 그대로다


# ---------- 실호출 허용 목록(커밋 뒤 통과) ----------
def test_the_approved_sets_are_the_three_coded_entries_and_ids_are_disjoint():
    sets = approved_sets.all_sets()
    assert [s.key for s in sets] == ["gen", "todo_routing", "chat_direct"]
    spec = sets[2]
    assert spec.ids == chat_direct_cases.IDS and spec.path == PATH
    assert not spec.ids & (sets[0].ids | sets[1].ids)
    assert runner._SET_ROWS["chat_direct"] == "committed_chat_direct_rows"


def test_the_committed_cases_pass_the_source_and_content_checks(items):
    runner.verify_committed(items, "dev")
    runner.verify_dev_source(PATH, items)
    assert set(runner.committed_chat_direct_rows()) == chat_direct_cases.IDS


def test_a_real_grant_for_ten_direct_cases_passes_the_runner_gate(items):
    ten = items[:10]
    options = RunOptions("r", mode="real", approved_usd=D("1"))
    with real_grant_scope(real_grant_for(ten)):
        assert runner._check_real_grant(ten, ten, [c.id for c in ten], options) is not None
    inp = SimpleNamespace(
        missing_ids=(),
        requested_ids=tuple(c.id for c in ten),
        items=ten,
        split="dev",
        source_file=PATH,
    )
    check = preflight._check_cases(inp)
    assert check.no == 7 and check.status == preflight.PASS, check.detail


def test_wrong_paths_tampered_cases_and_outsiders_are_refused(items, official_items, tmp_path):
    copy = tmp_path / "cases_chat_direct.json"
    copy.write_bytes(PATH.read_bytes())
    with pytest.raises(RunnerRefused, match="허용된 사례 파일"):
        runner.verify_dev_source(copy, items)
    with pytest.raises(RunnerRefused, match="허용된 사례 파일"):
        runner.verify_dev_source(OFFICIAL, items)
    with pytest.raises(RunnerRefused, match="소통 단독 평가 사례"):
        runner.verify_dev_source(PATH, [*items, official_items[0]])
    changed = items[0].model_copy(update={"question": items[0].question + " (바꿈)"})
    with pytest.raises(RunnerRefused, match="다르다"):
        runner.verify_committed([changed], "dev")
    with pytest.raises(RunnerRefused, match="목록에 없는"):
        runner.verify_committed([new_case("s-fcd-21-search", split="dev")], "dev")


def test_case_count_and_repeat_limits_are_unchanged():
    assert real_gate.MAX_REAL_CASES == 10 and real_gate.MAX_REAL_REPEAT == 3
    real_gate.check_request(
        approve_usd=D("0.1"), split="dev", case_ids=IDS[:10], repeat=3, require_env=False
    )
    with pytest.raises(real_gate.RealGateRefused):  # 20건을 한 번에 실호출할 수는 없다(10건씩)
        real_gate.check_request(
            approve_usd=D("0.1"), split="dev", case_ids=IDS, repeat=1, require_env=False
        )
