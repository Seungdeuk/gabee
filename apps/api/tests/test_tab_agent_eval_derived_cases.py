"""정산 평가 사례 중 모델이 계산해야 하는 값·여러 도구 사례의 정답을 시드에서 코드로 확인한다(LLM 없이).

도구 결과에 그대로 없는 값(차이·나눔·합)은 test_tab_agent_eval_cases.py 가 확인하지 못해서 skip_tool_check 로 두고 여기서 따로 본다."""

import json
from pathlib import Path

from sqlalchemy import select

from app.features.billing import agent as billing_agent
from app.features.family_group.models import User
from app.shared.db import SessionLocal
from evals.tab_agents.seed import seed, seed_child, seed_write_targets
from tests.helpers import join_family, signup

CASES = {
    c["id"]: c
    for c in json.loads(
        (Path(__file__).parents[1] / "evals/tab_agents/cases.json").read_text("utf-8")
    )
}


def _num(text: str) -> int:
    return int(text.replace(",", ""))


def _run(client, family, tool: str, args: dict, *more: tuple[str, dict]):
    """도구를 한 번(또는 같은 가족 데이터에서 여러 번) 돌린다. 여러 번이면 결과 목록을 돌려준다.
    evals/tab_agents/run.py 와 같은 순서로 가족을 만든다(민수가 가입한 3명 가족이라 7월 숙소는 33,333원씩 나뉜다)."""
    a, b, group = family
    seed(client, a, b)
    child = signup(client, "민수", "child")
    join_family(client, a, group["invite_code"], child)
    with SessionLocal() as db:
        seed_child(client, a, db.scalars(select(User).where(User.name == "민수")).first().id)
    seed_write_targets(client, a, b, child)
    with SessionLocal() as db:
        me = db.scalars(select(User).where(User.name == "지민")).first()
        tools = {t.name: t for t in billing_agent.build_tools(db, me.active_group_id, me, [])}
        outs = [tools[name].run(a) for name, a in ((tool, args), *more)]
        return outs if more else outs[0]


def test_oct_difference_between_two_payers(client, family):
    out = _run(client, family, "get_month_summary", {"month": "2026-10"})
    paid = {b["name"]: b["paid"] for b in out["balances"]}
    assert paid["지민"] - paid["수진"] == _num(CASES["b-calc-diff"]["expect_contains"][0])


def test_nov_split_between_two_payers(client, family):
    out = _run(client, family, "get_month_summary", {"month": "2026-11"})
    assert out["total"] // 2 == _num(CASES["b-calc-split-two"]["expect_contains"][0])
    assert out["total"] % 2 == 0


def test_nov_top_payer_is_jimin_with_80000(client, family):
    out = _run(client, family, "get_month_summary", {"month": "2026-11"})
    top = max(out["balances"], key=lambda b: b["paid"])
    assert top["name"] == "지민" and top["paid"] == _num(
        CASES["b-nov-top-payer"]["expect_contains"][1]
    )


def test_jul_transfers_sum_and_each(client, family):
    out = _run(client, family, "get_settlement", {"month": "2026-07"})
    amounts = {t["from_name"]: t["amount"] for t in out["transfers"]}
    assert amounts["수진"] == _num(CASES["b-settle-amount-jul"]["expect_contains"][0])
    assert sum(amounts.values()) == _num(CASES["b-settle-total-jul"]["expect_contains"][0])


def test_multi_tool_case_values_come_from_two_different_tools(client, family):
    case = CASES["b-multi-oct-jul"]
    summary, jul = _run(
        client,
        family,
        "get_month_summary",
        {"month": "2026-10"},
        ("get_settlement", {"month": "2026-07"}),
    )
    assert summary["total"] == _num(case["expect_contains"][0])
    assert set(case["tool_all"]) == {"get_month_summary", "get_settlement"}
    assert any(t["amount"] == _num(case["expect_contains"][1]) for t in jul["transfers"])


def test_parent_sees_child_allowance_balance(client, family):
    out = _run(client, family, "list_allowances", {})
    child = next(r for r in out["allowances"] if r["name"] == "민수")
    assert child["balance"] == _num(CASES["b-parent-allowance-balance"]["expect_contains"][0])
