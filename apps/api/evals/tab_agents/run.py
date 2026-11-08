"""탭 에이전트를 실제 LLM 으로 평가한다(ANTHROPIC_API_KEY 필요). 임시 SQLite 에 가짜 가족 데이터만 넣고 돌린다.

    cd apps/api && python -m evals.tab_agents.run [--case b-total] [--repeat 3]

사례마다 (1) 기대한 도구를 불렀는지(tool 이 null 이면 도구를 부르면 안 됨, tool_optional 이면 도구 사용은 채점 안 함)
(2) 답에 expect_contains 가 있는지 본다. as_user 로 질문하는 사람(기본 지민)을 고를 수 있다.
금액은 쉼표 있는/없는 형태를 모두 인정한다. 결과 표와 통과율만 출력하고 질문·답은 가짜 데이터라 그대로 보여 준다."""

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="gabee-eval-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/eval.db"  # 실제 DB 는 건드리지 않는다
os.environ["DATA_DIR"] = _tmp

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.features.ai_assistant.knowledge import rag_chat  # noqa: E402
from app.features.billing import agent as billing_agent  # noqa: E402
from app.features.billing import models as billing_models  # noqa: E402
from app.features.family_group.models import User  # noqa: E402
from app.main import app  # noqa: E402
from app.shared import ai_guard  # noqa: E402
from app.shared.config import settings  # noqa: E402
from app.shared.db import SessionLocal  # noqa: E402
from app.shared.errors import ApiError  # noqa: E402
from app.shared.llm import agent_guard  # noqa: E402
from app.shared.llm.agent import AgentReply  # noqa: E402
from evals import budget  # noqa: E402
from evals.tab_agents import scoring  # noqa: E402
from evals.tab_agents.seed import (  # noqa: E402
    seed,
    seed_child,
    seed_other_family,
    seed_write_targets,
)
from tests.helpers import join_family, signup  # noqa: E402

CASES = json.loads((Path(__file__).parent / "cases.json").read_text("utf-8"))
AGENTS = {"billing": billing_agent}
BILLING_TABLES = [
    m.__table__
    for m in vars(billing_models).values()
    if isinstance(m, type) and hasattr(m, "__table__") and m.__module__ == billing_models.__name__
]


def _contains(answer: str, text: str) -> bool:
    return text in answer or text.replace(",", "") in answer.replace(",", "")


def main() -> int:
    logging.basicConfig(level=logging.WARNING)  # 모델 호출 실패 원인(서버 로그)을 보여 준다
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", help="사례 id(여러 번 가능). 비우면 전체")
    parser.add_argument("--repeat", type=int, default=1, help="사례마다 반복 횟수")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="도구 인자·금액 근거·쓰기 없음도 통과 조건에 넣는다(기본은 따로 보여 주기만 한다)",
    )
    parser.add_argument(
        "--max-answers", type=int, help="답변 횟수(사례 수 × 반복) 상한. 넘으면 실행하지 않는다"
    )
    args = parser.parse_args()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY 가 설정되지 않아 실제 평가를 건너뜁니다.")
        return 2
    cases = [c for c in CASES if not args.case or c["id"] in args.case]
    budget.guard(
        "답변 = 사례 수 × 반복", budget.answer_calls(len(cases), args.repeat), args.max_answers
    )
    # 평가는 한 사용자가 짧은 시간에 많이 부르므로 하루 한도를 넉넉히 한다(실서비스 설정은 그대로)
    settings.ai_tab_agent_max_calls_per_user_per_day = 100000
    settings.ai_tab_agent_max_calls_per_group_per_day = 100000
    agent_guard.register()
    passed = total = 0
    args_total = args_good = amount_total = amount_bad = write_total = write_bad = 0
    per_case: dict[str, list[bool]] = {}
    with TestClient(app) as client:
        a = signup(client, "지민")
        group = client.post("/family-group/groups", json={"name": "평가 가족"}, headers=a).json()
        b = signup(client, "수진")
        join_family(client, a, group["invite_code"], b)  # 가입 요청 → 소유자 승인
        seed(client, a, b)
        child = signup(client, "민수", "child")
        join_family(client, a, group["invite_code"], child)
        with SessionLocal() as db:
            seed_child(client, a, db.scalars(select(User).where(User.name == "민수")).first().id)
        seed_write_targets(client, a, b, child)
        with SessionLocal() as db:  # 가족이 AI 를 켠 상태로 평가한다
            me = db.scalars(select(User).where(User.name == "지민")).first()
            ai_guard.set_enabled(db, me.active_group_id, me.id, True)
        seed_other_family(client, signup(client, "남"))
        for case in cases:
            for _ in range(args.repeat):
                with SessionLocal() as db:
                    me = db.scalars(
                        select(User).where(User.name == case.get("as_user", "지민"))
                    ).first()
                    fp_before = scoring.db_fingerprint(db, BILLING_TABLES)
                    if case["agent"] == "main":  # 메인이 맞는 탭 에이전트를 골라 묻는지
                        r = rag_chat.ask(
                            db,
                            me.active_group_id,
                            case["question"],
                            history=case.get("history"),
                            user=me,
                        )
                        answer, can_answer, calls = r.answer, r.source == "ai", r.tool_calls
                        used = [c["name"] for c in calls if c["name"].startswith("ask_")]
                        n_proposals = len(r.proposals)
                        summary_texts = [p.summary for p in r.proposals]
                        want = case.get("main_tools")  # 없으면 도구 선택은 채점하지 않는다
                        tool_ok = want is None or set(used) == set(want)
                    else:
                        try:
                            reply = AGENTS[case["agent"]].ask(
                                db,
                                me.active_group_id,
                                me,
                                case["question"],
                                history=case.get("history"),
                            )
                        except ApiError as e:  # 관문이 막은 경우(동의·한도·모델 실패)도 실패로 센다
                            reply = AgentReply(
                                f"[{e.status} {e.code}] {e.message}", can_answer=False
                            )
                        answer, can_answer = reply.answer, reply.can_answer
                        used = [c["name"] for c in reply.tool_calls]
                        n_proposals = len(reply.proposals)
                        summary_texts = [p.summary for p in reply.proposals]
                        if case.get("tool_optional"):
                            tool_ok = True
                        elif case.get("tool_any"):
                            tool_ok = any(t in used for t in case["tool_any"])
                        else:
                            tool_ok = (case["tool"] in used) if case["tool"] else not used
                text_ok = (
                    all(_contains(answer, t) for t in case["expect_contains"])
                    and (
                        not case.get("expect_any")
                        or any(_contains(answer, t) for t in case["expect_any"])
                    )
                    and not any(_contains(answer, t) for t in case.get("expect_not_contains", []))
                    and not any(
                        answer.strip().endswith(t) for t in case.get("expect_not_endswith", [])
                    )
                    and not any(re.search(r, answer) for r in case.get("expect_not_regex", []))
                )
                proposals_ok = n_proposals == case.get(
                    "expect_proposals", 0
                )  # 쓰기는 요청했을 때만
                summaries = " ".join(summary_texts)
                proposals_ok = proposals_ok and all(
                    t in summaries for t in case.get("expect_in_proposal", [])
                )
                ok = can_answer and tool_ok and text_ok and proposals_ok
                args_flag = write_ok = None
                bad_amounts: list[int] = []
                if case["agent"] != "main":  # 추가 채점: 도구 인자, 금액 근거, 쓰기 없음
                    with SessionLocal() as db2:
                        who = db2.scalars(
                            select(User).where(User.name == case.get("as_user", "지민"))
                        ).first()
                        write_ok = scoring.db_fingerprint(db2, BILLING_TABLES) == fp_before
                        tools = {
                            t.name: t
                            for t in AGENTS[case["agent"]].build_tools(
                                db2, who.active_group_id, who
                            )
                        }
                        outputs = []  # 모델이 부른 읽기 도구를 같은 인자로 다시 돌려 DB 값을 얻는다
                        for c in reply.tool_calls:
                            if c["name"] in tools and not c["name"].startswith("propose_"):
                                try:
                                    outputs.append(tools[c["name"]].run(c.get("input") or {}))
                                except Exception:  # noqa: BLE001 - 인자가 틀린 호출은 값이 없는 것으로 본다
                                    continue
                    history = " ".join(h.get("text", "") for h in case.get("history") or [])
                    args_flag = scoring.args_ok(case, reply.tool_calls)
                    bad_amounts = scoring.ungrounded_amounts(
                        answer, outputs, [case["question"], history, summaries]
                    )
                    if args.strict:
                        ok = ok and args_flag is not False and write_ok and not bad_amounts
                    if args_flag is not None:
                        args_total, args_good = args_total + 1, args_good + bool(args_flag)
                    write_total, write_bad = write_total + 1, write_bad + (not write_ok)
                    if scoring.amounts_in(answer):
                        amount_total, amount_bad = amount_total + 1, amount_bad + bool(bad_amounts)
                gap = bool(case.get("known_gap"))  # 알려진 한계: 통과율과 종료 코드에서 뺀다
                if not gap:
                    passed, total = passed + ok, total + 1
                per_case.setdefault(case["id"], []).append(ok)
                label = ("GAP-PASS" if ok else "GAP") if gap else ("PASS" if ok else "FAIL")
                extra = ""
                if case["agent"] != "main":
                    extra = (
                        f" 인자={'-' if args_flag is None else ('맞음' if args_flag else '틀림')}"
                        f" 쓰기없음={'예' if write_ok else '아니오'}"
                        f"{' 근거없는금액=' + str(bad_amounts) if bad_amounts else ''}"
                    )
                print(f"[{label}] {case['id']} tools={used}{extra}")
                if not ok and not gap:
                    print(f"    답: {answer[:200]}")
        print(chr(10) + "사례별 통과율")
        for cid, results in per_case.items():
            note = (
                " (알려진 한계)"
                if next(c for c in CASES if c["id"] == cid).get("known_gap")
                else ""
            )
            print(f"  {cid}: {sum(results)}/{len(results)}{note}")
    print(
        "\n추가 채점(정산): "
        f"도구 인자 {args_good}/{args_total}, "
        f"금액 근거 없음 {amount_bad}/{amount_total}(금액이 나온 답 기준, 계산한 금액은 근거 없음으로 나올 수 있음), "
        f"쓰기 발생 {write_bad}/{write_total}"
        + ("" if args.strict else " — 통과 조건에는 넣지 않음(--strict 로 포함)")
    )
    print(f"\n통과 {passed}/{total} (모델 {settings.llm_model})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
