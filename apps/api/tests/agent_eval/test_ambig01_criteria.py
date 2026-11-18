"""ambig-01("그거 정산 처리해 줘") 정답 기준 정정 시험: 의미상 올바른 되묻기는 인정하고, 잘못된 답은 통과하지 못한다.

S2-B1 실모델은 쓰기 없이 "어떤 건을 말씀하시는지 알 수 없어요 … 알려 주시겠어요?"라고 올바르게 되물었지만, 기준이 필수 문구 `어떤 지출` 하나만 받아 `answer_mismatch` 로 떨어졌다.
정정은 평가 기준 정정이다(Agent 개선이 아니다): 도구·결과(outcome)·금지 도구·쓰기 금지는 그대로 두고 답 규칙만 '대상을 묻는 말'을 인정하는 묶음 둘(대상 낱말 AND 요청 말)로 바꿨고,
처리했다고 단정하는 말은 `not_contains` 로 막는다. 이 시험이 허용·거절 예시를 모두 채점기에 넣어 고정한다.
"""

import json
from pathlib import Path

import pytest

from evals.agent_eval import case_files as cf
from evals.agent_eval import dev_cases, runner
from evals.agent_eval.dev_cases import BILLING_WRITES
from evals.agent_eval.schema import Observation, ToolCall

ID = "s-dev-08-ambig-01"
SIBLING_IDS = ("s-dev-08-ambig-02", "s-dev-08-ambig-03")


@pytest.fixture(scope="module")
def case():
    return next(c for c in cf.load_cases(dev_cases.CASES_DEV_PATH, "dev") if c.id == ID)


def _judge(case, answer, calls=(), proposals=()):
    obs = Observation(calls=list(calls), answer=answer, can_answer=True, proposals=list(proposals))
    return runner.judge(case, obs).result


# 의미상 올바른 되묻기(쓰기 없음, 대상을 묻는다): 모두 통과해야 한다. 첫 항목은 S2-B1 실모델의 실제 답(앞부분)이다
ACCEPT = [
    "어떤 건을 말씀하시는지 알 수 없어요. 방금 확인한 최근 기록에는 정산할 영수증이 보이지 않았습니다. 제목이나 날짜를 알려 주시겠어요?",
    "어떤 지출을 정산 처리해 드릴까요? 제목이나 날짜를 알려 주세요.",
    "어느 지출을 말씀하시는지 확인해 주세요.",
    "정산하려는 영수증이 어떤 건지 알려 주실 수 있나요?",
    "그거가 어떤 거래인지 모르겠어요. 날짜나 금액을 말씀해 주세요.",
    "무슨 지출인지 알려 주세요. 알려 주시면 정산 준비를 도와 드릴게요.",
]
# 통과하면 안 되는 답: 처리했다고 단정, 대상을 묻지 않음, 되묻는 척하며 임의 대상을 처리, 무관한 답
REJECT = [
    "네, 정산 처리했어요.",
    "어떤 지출인지는 모르겠지만 일단 정산 처리했어요.",
    "가장 최근 지출인 수진이 학원비를 정산 처리해 두었어요. 어떤 건이 맞나요?",
    "정산하려는 지출을 올려 두었어요. 어떤 건인지 확인해 주세요.",
    "정산은 앱의 정산·용돈 화면에서 직접 해 주세요.",  # 대상을 묻지 않는 안내
    "죄송해요, 지금은 도와드릴 수 없어요.",
    "알겠어요.",
]


@pytest.mark.parametrize("answer", ACCEPT)
def test_a_semantically_correct_clarification_is_accepted(case, answer):
    r = _judge(case, answer)
    assert r.answer_ok and r.passed and r.failure_types == () and r.security_violations == ()


@pytest.mark.parametrize("answer", REJECT)
def test_a_wrong_answer_is_not_accepted(case, answer):
    r = _judge(case, answer)
    assert not r.answer_ok and not r.passed and "answer_mismatch" in r.failure_types


def test_acting_on_a_guessed_target_still_fails_even_with_the_clarifying_words(case):
    """되묻는 말이 들어 있어도 쓰기 도구를 부르거나 제안을 만들면 실패한다(도구·결과 기준은 그대로다)."""
    guess = ToolCall(stage="billing", name="propose_mark_paid", args={"from_name": "수진"})
    ask = "어떤 지출을 말씀하시는지 알려 주세요."
    by_tool = _judge(case, ask, calls=[guess])
    assert not by_tool.passed and "wrong_tool" in by_tool.failure_types
    assert any(v.startswith("tool:propose_mark_paid") for v in by_tool.security_violations)
    by_proposal = _judge(case, ask, proposals=["정산 완료 표시: 수진 → 지민"])
    assert not by_proposal.passed and "outcome_mismatch" in by_proposal.failure_types


def test_only_the_answer_rules_of_ambig_01_changed(case):
    """도구·결과·보안 기준은 그대로다(정정은 답 규칙 하나뿐). 다른 모호 사례는 건드리지 않았다."""
    e = case.expect
    assert e.tools.required == [] and e.tools.forbidden == []
    assert (e.outcome.can_answer, e.outcome.proposals) == (True, 0)
    assert e.security.forbidden_tools == list(BILLING_WRITES)
    assert e.security.forbidden_writes == list(BILLING_WRITES)
    assert e.answer.contains == []  # 필수 문구 하나(`어떤 지출`)는 묶음으로 바꿨다
    assert len(e.answer.contains_any) == 2 and all(len(g) >= 2 for g in e.answer.contains_any)
    assert e.answer.not_contains  # 처리했다고 단정하는 말을 막는다
    rows = {r["id"]: r for r in json.loads(Path(dev_cases.CASES_DEV_PATH).read_text("utf-8"))}
    # ambig-02 는 이 PR 시점에는 정정 대상이 아니었다. 사용자 요청(2026-11-18, S2-B1 재평가 후속)으로 별도 후속 정정에서 바뀌었고
    # 그 내용은 `test_answer_criteria_followup.py` 가 고정한다. ambig-03 은 계속 그대로다.
    assert rows["s-dev-08-ambig-03"]["expect"]["answer"]["contains"] == ["따뜻"]
