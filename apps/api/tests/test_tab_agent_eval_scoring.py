"""정산 에이전트 평가의 추가 채점 함수 시험(LLM 없이)."""

import pytest
from sqlalchemy import select

from app.features.billing import models as billing_models
from app.features.billing.models import Expense
from app.shared.db import SessionLocal
from evals import budget
from evals.tab_agents import scoring


def test_amounts_are_read_from_won_phrases():
    assert scoring.amounts_in("총 86,000원이고 수진이 5만원, 1000 원 냈어요") == {
        86000,
        50000,
        1000,
    }
    assert scoring.amounts_in("10월 12일에 3건") == set()


def test_ungrounded_amounts_use_tool_output_question_and_context():
    out = [{"total": 60000, "items": [{"title": "진료비", "amount": 30000}]}]
    assert scoring.ungrounded_amounts("합계 60,000원, 진료비 30,000원", out, []) == []
    assert scoring.ungrounded_amounts("합계 70,000원", out, []) == [70000]
    assert (
        scoring.ungrounded_amounts("치과 50,000원 추가할까요?", out, ["치과 50000원 추가해줘"])
        == []
    )


def test_args_ok_compares_name_and_input():
    case = {"tool": "get_month_summary", "tool_args": {"month": "2026-10"}}
    assert (
        scoring.args_ok(case, [{"name": "get_month_summary", "input": {"month": "2026-10"}}])
        is True
    )
    assert (
        scoring.args_ok(case, [{"name": "get_month_summary", "input": {"month": "2026-09"}}])
        is False
    )
    assert scoring.args_ok(case, []) is False
    assert scoring.args_ok({"tool": "propose_add_expense", "tool_args": {}}, []) is None
    assert scoring.args_ok({"tool": None}, []) is None


def test_fingerprint_changes_only_when_billing_rows_change(client, family):
    a, _, _ = family
    tables = [billing_models.Expense.__table__]
    with SessionLocal() as db:
        before = scoring.db_fingerprint(db, tables)
        assert scoring.db_fingerprint(db, tables) == before
    r = client.post(
        "/billing/expenses", json={"title": "x", "amount": 1000, "date": "2026-10-01"}, headers=a
    )
    assert r.status_code == 201
    with SessionLocal() as db:
        assert scoring.db_fingerprint(db, tables) != before
        row = db.scalars(select(Expense)).first()
        mid = scoring.db_fingerprint(db, tables)
        row.amount = row.amount + 1  # 개수가 같아도 값이 바뀌면 지문이 달라진다
        db.flush()
        assert scoring.db_fingerprint(db, tables) != mid


def test_budget_formulas_and_guard(capsys):
    assert budget.question_gen_calls(326, 2, 10) == 66
    assert budget.answer_calls(100, 3) == 300
    assert budget.judge_calls(300) == 300 and budget.judge_calls(300, 4) == 1200
    assert budget.loop_calls(budget.total(66, 300, 300), 5) == 3330
    budget.guard("시험", 10, 10)  # 상한과 같으면 통과
    with pytest.raises(SystemExit):
        budget.guard("시험", 11, 10)
    with pytest.raises(ValueError):
        budget.question_gen_calls(1, 1, 0)
