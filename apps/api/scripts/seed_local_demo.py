"""로컬 개발 DB 에 정산·지출·용돈 가짜 데이터를 채운다(데모 가족 한 팀). 공용 DB 에는 절대 쓰지 않는다.

    cd apps/api
    DATABASE_URL=postgresql+psycopg://postgres:<비번>@127.0.0.1:5433/gabee python -m scripts.seed_local_demo

- DATABASE_URL 의 호스트가 127.0.0.1 / localhost 가 아니면 아무것도 하지 않고 끝낸다(공용 DB 보호).
- 이미 '데모 가족' 이 있으면 다시 만들지 않는다(여러 번 실행해도 데이터가 늘지 않는다).
- 가짜 계정 3명(지민·수진 보호자, 민수 자녀)은 임시 토큰(X-Gyeot-Token)으로 만들며 끝에 토큰을 출력한다. /docs 에서 시험하는 용도다.
- 가족의 AI 동의를 켜 둔다(정산·돌봄 에이전트를 시험하려면 필요하다).
"""

import sys
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.shared.config import settings

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
FAMILY_NAME = "데모 가족"
KST = timezone(timedelta(hours=9))


def _check_local() -> None:
    host = make_url(settings.database_url).host
    if host not in LOCAL_HOSTS:
        print(
            f"DATABASE_URL 의 호스트가 로컬이 아니라서 중단합니다: {host!r} (127.0.0.1 / localhost 만 허용)"
        )
        sys.exit(2)


def _ok(response, *codes: int):
    assert response.status_code in (codes or (200, 201)), (response.status_code, response.text)
    return response.json() if response.content else None


def main() -> int:
    _check_local()
    from app.features.family_group.models import Group, User
    from app.main import app
    from app.shared import ai_guard
    from app.shared.db import SessionLocal
    from tests.helpers import join_family, signup

    with SessionLocal() as db:
        if db.scalars(select(Group).where(Group.name == FAMILY_NAME)).first():
            print(f"'{FAMILY_NAME}' 가 이미 있어서 아무것도 만들지 않습니다.")
            return 0

    today = datetime.now(KST).date()
    first_this = today.replace(day=1)
    last_month = first_this - timedelta(days=1)

    def day_in(month_start: date, day: int) -> str:
        return min(month_start.replace(day=day), today).isoformat()

    with TestClient(app) as client:
        a = signup(client, "지민", "parent")
        group = _ok(client.post("/family-group/groups", json={"name": FAMILY_NAME}, headers=a))
        b = signup(client, "수진", "parent")
        c = signup(client, "민수", "child")
        join_family(client, a, group["invite_code"], b)
        join_family(client, a, group["invite_code"], c)

        # ---- 정산: 이번 달·지난달 지출, 구독, 용돈 ----
        this_m = [
            ("장보기", 54300, "식비", b, 3),
            ("병원 진료비", 32000, "의료", a, 5),
            ("약국", 12500, "의료", a, 5),
            ("택시", 8900, "교통", b, 9),
            ("전기요금", 48200, "생활", a, 12),
            ("외식", 67000, "식비", b, 15),
            ("영화", 24000, "문화", a, 18),
        ]
        prev_m = [
            ("장보기", 61200, "식비", b, 4),
            ("가스요금", 29800, "생활", a, 10),
            ("병원 진료비", 18000, "의료", a, 20),
            ("외식", 52000, "식비", b, 25),
        ]
        for rows, month_start in ((this_m, first_this), (prev_m, last_month.replace(day=1))):
            for title, amount, category, who, day in rows:
                body = {"title": title, "amount": amount, "category": category}
                body["date"] = (
                    day_in(month_start, day)
                    if month_start == first_this
                    else month_start.replace(day=min(day, 28)).isoformat()
                )
                _ok(client.post("/billing/expenses", json=body, headers=who))
        for body, who in (
            ({"kind": "ott", "name": "넷플릭스", "monthly_fee": 17000, "billing_day": 15}, a),
            (
                {"kind": "ott", "name": "유튜브 프리미엄", "monthly_fee": 14900, "billing_day": 22},
                b,
            ),
            (
                {
                    "kind": "telecom",
                    "name": "휴대폰 요금",
                    "carrier": "skt",
                    "monthly_fee": 55000,
                    "billing_day": 25,
                },
                a,
            ),
        ):
            _ok(client.post("/billing/subscriptions", json=body, headers=who))
        with SessionLocal() as db:
            child_id = db.scalars(select(User).where(User.name == "민수")).first().id
        plan = {"cycle": "monthly", "day": 1, "amount": 30000, "mode": "remind"}
        _ok(client.put(f"/billing/allowances/{child_id}/plan", json=plan, headers=a))
        _ok(
            client.post(
                f"/billing/allowances/{child_id}/credits",
                json={"amount": 30000, "memo": "이번 달 용돈"},
                headers=a,
            ),
            200,
            201,
        )

        # ---- 가족의 AI 동의 켜기 ----
        with SessionLocal() as db:
            owner = db.scalars(select(User).where(User.name == "지민")).first()
            ai_guard.set_enabled(db, owner.active_group_id, owner.id, True)

    print(f"'{FAMILY_NAME}' 를 만들고 정산·돌봄 가짜 데이터를 채웠습니다.")
    print("임시 토큰(헤더 X-Gyeot-Token):")
    for name, headers in (("지민(보호자·소유자)", a), ("수진(보호자)", b), ("민수(자녀)", c)):
        print(f"  {name}: {headers['X-Gyeot-Token']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
