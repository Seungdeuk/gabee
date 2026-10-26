"""evals/tab_agents/cases.json 이 시드 데이터와 맞는지 확인한다(LLM 없이, 도구 결과 기준).

정답 기대값이 틀린 평가셋으로 모델을 평가하지 않도록, 각 사례의 도구를 직접 돌려 expect_contains 가 나오는지 본다."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.features.billing import agent as billing_agent
from app.features.care import agent as care_agent
from app.features.family_group.models import User
from app.shared.db import SessionLocal
from evals.tab_agents.seed import seed

CASES = json.loads((Path(__file__).parents[1] / "evals/tab_agents/cases.json").read_text("utf-8"))
AGENTS = {"billing": billing_agent, "care": care_agent}


def test_case_ids_are_unique_and_tools_exist(client, family):
    assert len({c["id"] for c in CASES}) == len(CASES)
    from app.features.ai_assistant.agents import AGENTS as MAIN_AGENT_TOOLS

    for c in (c for c in CASES if c["agent"] == "main"):
        assert set(c.get("main_tools", [])) <= set(MAIN_AGENT_TOOLS), c["id"]
    with SessionLocal() as db:
        me = db.scalars(select(User).where(User.name == "지민")).first()
        for agent_name, module in AGENTS.items():
            names = {t.name for t in module.build_tools(db, me.active_group_id, me, [])}
            for c in (c for c in CASES if c["agent"] == agent_name and c["tool"]):
                assert c["tool"] in names, c["id"]


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c["tool"] and not c["tool"].startswith("propose_")],
    ids=lambda c: c["id"],
)
def test_expected_values_appear_in_tool_output(client, family, case):
    a, b, _ = family
    seed(client, a, b)
    with SessionLocal() as db:
        me = db.scalars(select(User).where(User.name == "지민")).first()
        tools = {t.name: t for t in AGENTS[case["agent"]].build_tools(db, me.active_group_id, me)}
        out = json.dumps(tools[case["tool"]].run(case["tool_args"]), ensure_ascii=False)
    for text in case["expect_contains"]:
        # 금액은 도구 결과에는 쉼표 없는 숫자로 나오므로 둘 다 본다
        assert text in out or text.replace(",", "") in out, (case["id"], text)
