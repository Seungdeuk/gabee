"""탭 에이전트를 실제 LLM 으로 평가한다(ANTHROPIC_API_KEY 필요). 임시 SQLite 에 가짜 가족 데이터만 넣고 돌린다.

    cd apps/api && python -m evals.tab_agents.run [--case b-total] [--repeat 3]

사례마다 (1) 기대한 도구를 불렀는지(tool 이 null 이면 도구를 부르면 안 됨) (2) 답에 expect_contains 가 있는지 본다.
금액은 쉼표 있는/없는 형태를 모두 인정한다. 결과 표와 통과율만 출력하고 질문·답은 가짜 데이터라 그대로 보여 준다."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="gabee-eval-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/eval.db"  # 실제 DB 는 건드리지 않는다
os.environ["DATA_DIR"] = _tmp

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.features.billing import agent as billing_agent  # noqa: E402
from app.features.care import agent as care_agent  # noqa: E402
from app.features.family_group.models import User  # noqa: E402
from app.main import app  # noqa: E402
from app.shared.config import settings  # noqa: E402
from app.shared.db import SessionLocal  # noqa: E402
from evals.tab_agents.seed import seed  # noqa: E402
from tests.helpers import signup  # noqa: E402

CASES = json.loads((Path(__file__).parent / "cases.json").read_text("utf-8"))
AGENTS = {"billing": billing_agent, "care": care_agent}


def _contains(answer: str, text: str) -> bool:
    return text in answer or text.replace(",", "") in answer.replace(",", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", help="사례 id(여러 번 가능). 비우면 전체")
    parser.add_argument("--repeat", type=int, default=1, help="사례마다 반복 횟수")
    args = parser.parse_args()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY 가 설정되지 않아 실제 평가를 건너뜁니다.")
        return 2
    cases = [c for c in CASES if not args.case or c["id"] in args.case]
    passed = total = 0
    with TestClient(app) as client:
        a = signup(client, "지민")
        group = client.post("/family-group/groups", json={"name": "평가 가족"}, headers=a).json()
        b = signup(client, "수진")
        client.post("/family-group/groups/join", json={"code": group["invite_code"]}, headers=b)
        seed(client, a, b)
        for case in cases:
            for _ in range(args.repeat):
                with SessionLocal() as db:
                    me = db.scalars(select(User).where(User.name == "지민")).first()
                    reply = AGENTS[case["agent"]].ask(db, me.active_group_id, me, case["question"])
                used = [c["name"] for c in reply.tool_calls]
                tool_ok = (case["tool"] in used) if case["tool"] else not used
                text_ok = all(_contains(reply.answer, t) for t in case["expect_contains"])
                ok = reply.can_answer and tool_ok and text_ok
                passed, total = passed + ok, total + 1
                print(f"[{'PASS' if ok else 'FAIL'}] {case['id']} tools={used}")
                if not ok:
                    print(f"    답: {reply.answer[:200]}")
    print(f"\n통과 {passed}/{total} (모델 {settings.llm_model})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
