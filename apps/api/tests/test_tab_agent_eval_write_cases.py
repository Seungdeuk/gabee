"""평가셋의 쓰기 제안 사례가 시드 데이터와 맞는지 확인한다(LLM 없이, 제안 도구를 직접 불러서).

정답 기대값이 틀린 평가셋으로 모델을 평가하지 않도록, 제안이 만들어져야 하는 사례는 요약문(expect_in_proposal)을,
막혀야 하는 사례는 도구가 거절하는지를 본다."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.features.billing import agent as billing_agent
from app.features.care import agent as care_agent
from app.features.family_group.models import User
from app.shared.db import SessionLocal
from evals.tab_agents.seed import seed, seed_write_targets
from tests.helpers import join_family, signup

pytestmark = pytest.mark.usefixtures(
    "full_care_samples"
)  # 평가 데이터는 물·산책·컨디션 항목이 있는 예전 기본 세트를 쓴다

CASES = {
    c["id"]: c
    for c in json.loads(
        (Path(__file__).parents[1] / "evals/tab_agents/cases.json").read_text("utf-8")
    )
}
AGENTS = {"billing": billing_agent, "care": care_agent}


def _expense_id(client, headers, month, title):
    rows = client.get("/billing/expenses", params={"month": month}, headers=headers).json()
    return next(e["id"] for e in rows if e["title"] == title)


def _setup(client, family):
    a, b, group = family
    child = signup(client, "민수", "child")
    join_family(client, a, group["invite_code"], child)
    seed(client, a, b)
    seed_write_targets(client, a, b, child)
    return a, b


def _request_id(client, headers):
    members = client.get("/family-group/groups/me", headers=headers).json()["members"]
    child_id = next(m["id"] for m in members if m["name"] == "민수")
    row = next(
        r
        for r in client.get("/billing/allowances", headers=headers).json()
        if r["child_id"] == child_id
    )
    return row["requests"][0]["id"]


def _args(client, a):
    """사례 id → (사용자 이름, 도구 이름, 도구 인자). LLM 이 도구 결과를 보고 고를 인자를 그대로 적는다."""
    dental = _expense_id(client, a, "2026-06", "치과 진료")
    snack = _expense_id(client, a, "2026-06", "수진 간식")
    trip = _expense_id(client, a, "2026-07", "여행 숙소")
    rid = _request_id(client, a)
    daily = client.get("/care/daily", params={"date": "2026-10-18"}, headers=a).json()
    by_name = {i["name"]: i["id"] for i in daily["items"]}
    day = "2026-10-18"
    return {
        "b-update-amount": (
            "지민",
            "propose_update_expense",
            {"expense_id": dental, "amount": 50000},
        ),
        "b-update-others": (
            "지민",
            "propose_update_expense",
            {"expense_id": snack, "amount": 5000},
        ),
        "b-update-settled": (
            "지민",
            "propose_update_expense",
            {"expense_id": trip, "amount": 90000},
        ),
        "b-delete-own": ("지민", "propose_delete_expense", {"expense_id": dental}),
        "b-delete-others": ("지민", "propose_delete_expense", {"expense_id": snack}),
        "b-delete-settled": ("지민", "propose_delete_expense", {"expense_id": trip}),
        "b-paid-propose": (
            "지민",
            "propose_mark_paid",
            {"month": "2026-07", "from_name": "수진", "to_name": "지민"},
        ),
        "b-allowance-approve": (
            "지민",
            "propose_decide_allowance_request",
            {"child_name": "민수", "request_id": rid, "decision": "approve"},
        ),
        "b-allowance-approve-amount": (
            "지민",
            "propose_decide_allowance_request",
            {"child_name": "민수", "request_id": rid, "decision": "approve", "amount": 3000},
        ),
        "b-allowance-reject": (
            "지민",
            "propose_decide_allowance_request",
            {"child_name": "민수", "request_id": rid, "decision": "reject"},
        ),
        "b-allowance-not-manager": (
            "수진",
            "propose_decide_allowance_request",
            {"child_name": "민수", "request_id": rid, "decision": "approve"},
        ),
        "c-clear-meal-own": ("지민", "propose_clear_meal", {"meal": "lunch", "date": "2026-10-20"}),
        "c-clear-meal-others": ("지민", "propose_clear_meal", {"meal": "dinner", "date": day}),
        "c-clear-item-own": (
            "지민",
            "propose_clear_item",
            {"item_id": by_name["영양제"], "date": day},
        ),
        "c-clear-item-others": (
            "지민",
            "propose_clear_item",
            {"item_id": by_name["산책"], "date": day},
        ),
    }


WRITE_IDS = [
    "b-update-amount",
    "b-update-others",
    "b-update-settled",
    "b-delete-own",
    "b-delete-others",
    "b-delete-settled",
    "b-paid-propose",
    "b-allowance-approve",
    "b-allowance-approve-amount",
    "b-allowance-reject",
    "b-allowance-not-manager",
    "c-clear-meal-own",
    "c-clear-meal-others",
    "c-clear-item-own",
    "c-clear-item-others",
]


@pytest.mark.parametrize("case_id", WRITE_IDS)
def test_write_case_matches_the_seed(client, family, case_id):
    a, _ = _setup(client, family)
    user_name, tool_name, args = _args(client, a)[case_id]
    case = CASES[case_id]
    assert case["tool"] == tool_name
    with SessionLocal() as db:
        me = db.scalars(select(User).where(User.name == user_name)).first()
        proposed: list = []
        tools = {
            t.name: t
            for t in AGENTS[case["agent"]].build_tools(db, me.active_group_id, me, proposed)
        }
        if case["expect_proposals"] == 0:
            with pytest.raises(ValueError):
                tools[tool_name].run(args)
            assert proposed == []
        else:
            tools[tool_name].run(args)
            assert len(proposed) == case["expect_proposals"]
            summaries = " ".join(p.summary for p in proposed)
            for text in case["expect_in_proposal"]:
                assert text in summaries, (case_id, text, summaries)
