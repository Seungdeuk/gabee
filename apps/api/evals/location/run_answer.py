"""위치 기록 질문 에이전트를 실제 LLM 으로 평가한다(ANTHROPIC_API_KEY 필요). 임시 SQLite 에 가짜 가족 데이터만 넣고 돌린다.

    cd apps/api && python -m evals.location.run_answer [--case q-001] [--repeat 3] [--embedder e5|hash] [--dry-run]

사례마다 (1) 기대한 도구 사용 여부(tool_expected 가 null 이면 도구를 부르면 안 됨), (2) 답에 must_contain 이 있는지(같은 뜻의 표현과
숫자 표기 차이는 인정), (3) must_not_contain 이 없는지, (4) 규칙 점검: 좌표 모양의 숫자가 없는지, 답에 나온 장소 이름이 도구가
가져온 문장에 있는지(지어내기 점검)를 본다. 범위 밖 질문(out_of_scope)은 도구를 안 불렀고 금지어가 없으면 맞다고 본다 —
기대 문구가 질문의 낱말을 따라 적혀 있어 이 에이전트가 답할 수 있는 범위를 벗어난다.

--dry-run 은 LLM 대신 도구를 한 번 부르고 끝내는 가짜 모델을 끼워 배선만 확인한다(점수는 의미 없다).
실제 위치 데이터로는 평가하지 않는다.
"""

import argparse
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone

_tmp = tempfile.mkdtemp(prefix="gabee-loc-answer-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/eval.db"  # 실제 DB 는 건드리지 않는다
os.environ["DATA_DIR"] = _tmp

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.features.family_group.models import User  # noqa: E402
from app.features.location import agent, rag  # noqa: E402
from app.main import app  # noqa: E402
from app.shared import ai_guard  # noqa: E402
from app.shared.config import settings  # noqa: E402
from app.shared.db import SessionLocal  # noqa: E402
from app.shared.errors import ApiError  # noqa: E402
from evals.location.run_retrieval import EXCLUDED, build_spans, make_embedder  # noqa: E402
from evals.location.validate import load  # noqa: E402
from tests.helpers import join_family, signup  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 10, 9, 0, tzinfo=KST)
ROLES = {"parent": "parent", "child": "child", "grandparent": "other"}  # 가입 화면의 역할
# 같은 뜻의 표현(기대 문구 → 인정할 표현). 숫자 횟수는 아래에서 자동으로 넓힌다.
ALIASES = {
    "권한이 없어": ["권한이 없", "볼 수 없", "접근할 수 없", "확인할 수 없"],
    "기록이 없어": [
        "기록이 없",
        "기록은 없",
        "기록을 찾을 수 없",
        "기록은 찾을 수 없",
        "찾을 수 없",
        "기록되어 있지 않",
    ],
    "위치 기록이 없어": ["기록이 없", "기록은 없", "기록되어 있지 않"],
    "위치 공유가 일시정지": ["일시정지", "일시 정지", "멈춰", "멈춘", "중단"],
    "동의하지 않아": ["동의하지 않", "동의 안", "동의하지않"],
    "이상 위치 기록": ["이상 위치", "평소 활동 구역 밖", "평소와 다른", "평소 동선"],
    "여행 모드": ["여행 모드", "여행모드", "여행"],
    "새벽": ["새벽", "01:10", "1시", "오전 1"],
}
MEANINGLESS_FORBIDDEN = {
    "실제 주소",
    "여행지 이름",
    "카페에 있었다고 단정",
}  # 답에 나올 말이 아니라서 검사하지 않는다
# 질문 데이터의 금지어가 정답과 겹쳐 올바른 답을 틀렸다고 하는 경우(케이스를 고치기 전까지 이 검사에서만 뺀다)
IGNORED_FORBIDDEN = {
    "q-013": (
        "집",
    ),  # '병원 다음에 어디'의 정답 설명에 시장 다음의 귀가("집으로 이동")를 덧붙인 답도 맞다
    "q-035": (
        "온유 병원",
    ),  # 하준은 같은 날 온유 병원을 거쳐 행복 약국·병원에 갔으므로 그렇게 말한 답도 맞다
}
COORD = re.compile(r"\d{2,3}\.\d{3,}")


def variants(phrase: str) -> list[str]:
    m = re.fullmatch(r"(\d+)번", phrase)
    if m:
        n = m.group(1)
        return [f"{n}번", f"{n}회", f"{n}차례", f"{n}건"]
    return ALIASES.get(phrase, [phrase])


def has(answer: str, phrase: str) -> bool:
    return any(v in answer for v in variants(phrase))


def dry_post(body: dict) -> dict:
    """배선 확인용 가짜 모델: 첫 호출에 질문 그대로 검색하고, 다음 호출에 도구 결과 첫 줄을 답으로 돌려준다."""
    usage = {"input_tokens": 1, "output_tokens": 1}
    last = body["messages"][-1]
    if isinstance(last["content"], str):
        return {
            "content": [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "search_location_history",
                    "input": {"query": last["content"]},
                }
            ],
            "usage": usage,
        }
    return {"content": [{"type": "text", "text": "dry-run"}], "usage": usage}


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append", help="사례 id(여러 번 가능). 비우면 전체")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--embedder", choices=["e5", "hash"], default="e5")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.dry_run and not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY 가 설정되지 않아 실제 평가를 건너뜁니다(배선만 보려면 --dry-run).")
        return 2

    if args.dry_run:
        settings.anthropic_api_key = (
            "dry-run"  # 관문이 키 유무를 먼저 본다. 실제 호출은 가짜 모델이 대신한다
        )
    scenario, cases = load()
    cases = [
        c for c in cases if (not args.case or c["id"] in args.case) and c["id"] not in EXCLUDED
    ]
    person_names = {p["id"]: p["name"] for p in scenario["people"]}
    place_names = [p["name"] for p in scenario["places"]]
    embedder = make_embedder(args.embedder)
    settings.ai_location_agent_max_calls_per_user_per_day = 100000  # 평가는 짧은 시간에 많이 부른다
    settings.ai_location_agent_max_calls_per_group_per_day = 100000
    agent.register()
    recorded: list[str] = []  # 이번 질문에서 도구가 가져온 문장
    real_search = rag.search

    def recording_search(*a, **kw):
        found = real_search(*a, **kw)
        recorded.extend(c.text for c, _ in found)
        return found

    rag.search = recording_search
    passed = total = 0
    per_case: dict[str, list[bool]] = {}
    with TestClient(app) as client:
        heads = {
            n: signup(client, n, ROLES[p["role"]]) for p in scenario["people"] for n in [p["name"]]
        }
        owner = person_names["jimin"]
        group = client.post(
            "/family-group/groups", json={"name": "평가 가족"}, headers=heads[owner]
        ).json()
        for name, headers in heads.items():
            if name != owner:
                join_family(client, heads[owner], group["invite_code"], headers)
        with SessionLocal() as db:
            users = {u.name: u for u in db.scalars(select(User))}
            gid = users[owner].active_group_id
            ai_guard.set_enabled(db, gid, users[owner].id, True)
            user_ids = {pid: users[name].id for pid, name in person_names.items()}
            n = rag.index_spans(db, gid, user_ids, build_spans(scenario), embedder)
            db.commit()
        print(
            f"임베더 {embedder.name}, 조각 {n}개, 평가 시계 {NOW:%Y-%m-%d}, 모델 {settings.llm_model}"
        )
        for case in cases:
            for _ in range(args.repeat):
                recorded.clear()
                with SessionLocal() as db:
                    me = db.get(User, user_ids[case["as_user"]])
                    try:
                        reply = agent.ask(
                            db,
                            gid,
                            me,
                            case["question"],
                            post=dry_post if args.dry_run else None,
                            today=NOW,
                            embedder=embedder,
                        )
                        answer, can_answer = reply.answer, reply.can_answer
                        used = [c["name"] for c in reply.tool_calls]
                    except ApiError as e:  # 관문이 막은 경우(동의·한도·모델 실패)도 실패로 센다
                        answer, can_answer, used = f"[{e.status} {e.code}] {e.message}", False, []
                kind = case["type"]
                expect_tool = case["tool_expected"] is not None
                tool_ok = bool(used) if expect_tool else not used
                if kind == "out_of_scope":
                    contain_ok = True
                else:
                    contain_ok = all(has(answer, t) for t in case["must_contain"])
                forbidden = [
                    t
                    for t in case["must_not_contain"]
                    if t not in MEANINGLESS_FORBIDDEN
                    and t not in IGNORED_FORBIDDEN.get(case["id"], ())
                ]
                if kind == "out_of_scope":
                    # 거절 문장에도 '위치 기록'이 들어가므로 금지어 대신 '위치 사실(장소 이름)을 말하지 않았는지'를 본다
                    forbid_ok = not any(p in answer for p in place_names)
                else:
                    forbid_ok = not any(t in answer for t in forbidden)
                rules = []
                if COORD.search(answer):
                    rules.append("좌표 모양 숫자")
                grounded = " ".join(recorded)
                invented = [p for p in place_names if p in answer and p not in grounded]
                if used and invented and not has(answer, "권한이 없어"):
                    rules.append(f"가져온 문장에 없는 장소: {invented}")
                ok = can_answer and tool_ok and contain_ok and forbid_ok and not rules
                if args.dry_run:
                    ok = can_answer and tool_ok if expect_tool else can_answer
                passed, total = passed + ok, total + 1
                per_case.setdefault(case["id"], []).append(ok)
                print(f"[{'PASS' if ok else 'FAIL'}] {case['id']} {kind} tools={used}")
                if not ok:
                    why = [
                        w
                        for w, bad in (
                            ("도구 사용", not tool_ok),
                            ("필수 문구", not contain_ok),
                            ("금지 문구", not forbid_ok),
                            ("답 못함", not can_answer),
                        )
                        if bad
                    ] + rules
                    print(f"    사유: {why}  질문: {case['question']}")
                    print(f"    답: {answer[:200]}")
        print("\n유형별 통과율")
        by_type: dict[str, list[bool]] = {}
        for c in cases:
            by_type.setdefault(c["type"], []).extend(per_case.get(c["id"], []))
        for t, rs in by_type.items():
            print(f"  {t:<14}{sum(rs)}/{len(rs)}")
    print(f"\n통과 {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
