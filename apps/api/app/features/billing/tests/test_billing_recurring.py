"""구독료를 월별 지출로 만들기: 결제한 사람·나눌 사람, 중복 방지, 날짜 계산, 정산 연결."""

from sqlalchemy import select

from app.features.billing.models import Expense
from app.shared.db import SessionLocal
from tests.helpers import signup


def _family(client, family):
    """엄마(parent) + 지민·수진(child). (지민 헤더, 헤더 모음, id 모음)."""
    a, b, group = family
    mom = signup(client, "엄마", role="parent")
    client.post("/family-group/groups/join", json={"code": group["invite_code"]}, headers=mom)
    members = client.get("/family-group/groups/me", headers=a).json()["members"]
    return a, {"지민": a, "수진": b, "엄마": mom}, {m["name"]: m["id"] for m in members}


def _add(client, headers, **body):
    r = client.post("/billing/subscriptions", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _plan(client, headers, month="2026-10"):
    r = client.get("/billing/subscriptions/monthly", params={"month": month}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _generate(client, headers, month="2026-10"):
    return client.post("/billing/subscriptions/monthly", json={"month": month}, headers=headers)


def _states(plan):
    return {i["name"]: i["state"] for i in plan["items"]}


def test_payer_defaults_to_the_requester_and_split_defaults_to_everyone(client, family):
    a, hdr, ids = _family(client, family)
    item = _add(client, hdr["수진"], kind="ott", name="티빙", monthly_fee=9500)
    assert item["payer_id"] == ids["수진"] and item["payer_name"] == "수진"
    assert set(item["split_among"]) == set(ids.values())  # 비우면 가족 전체


def test_explicit_null_payer_means_no_payer_while_omitting_means_the_requester(client, family):
    a, hdr, ids = _family(client, family)
    omitted = _add(client, hdr["수진"], kind="ott", name="안 보냄", monthly_fee=1000)
    assert omitted["payer_id"] == ids["수진"]
    explicit = _add(
        client, hdr["수진"], kind="ott", name="null 보냄", monthly_fee=1000, payer_id=None
    )
    assert explicit["payer_id"] is None and explicit["payer_name"] == ""
    assert _states(_plan(client, a))["null 보냄"] == "no_payer"


def test_payer_and_split_validation_and_patch(client, family):
    a, hdr, ids = _family(client, family)
    body = {"kind": "ott", "name": "웨이브", "monthly_fee": 7000}
    assert (
        client.post(
            "/billing/subscriptions", json={**body, "payer_id": "nobody"}, headers=a
        ).json()["code"]
        == "invalid_payer"
    )
    assert (
        client.post(
            "/billing/subscriptions", json={**body, "split_among": ["nobody"]}, headers=a
        ).json()["code"]
        == "invalid_split"
    )

    item = _add(client, a, **body, payer_id=ids["엄마"], split_among=[ids["지민"], ids["수진"]])
    assert item["payer_name"] == "엄마" and set(item["split_among"]) == {ids["지민"], ids["수진"]}
    url = f"/billing/subscriptions/{item['id']}"
    r = client.patch(url, json={"payer_id": ids["지민"]}, headers=a).json()
    assert r["payer_name"] == "지민" and set(r["split_among"]) == {
        ids["지민"],
        ids["수진"],
    }  # 나눌 사람은 그대로
    r = client.patch(url, json={"split_among": []}, headers=a).json()
    assert set(r["split_among"]) == set(ids.values())  # 빈 목록 = 가족 전체
    r = client.patch(url, json={"payer_id": None}, headers=a).json()
    assert r["payer_id"] is None and r["payer_name"] == ""
    assert (
        client.patch(url, json={"payer_id": "nobody"}, headers=a).json()["code"] == "invalid_payer"
    )
    assert (
        client.patch(url, json={"split_among": ["nobody"]}, headers=a).json()["code"]
        == "invalid_split"
    )


def test_plan_states(client, family):
    a, hdr, ids = _family(client, family)
    _add(client, a, kind="ott", name="준비됨", monthly_fee=10000, billing_day=3)
    _add(client, a, kind="ott", name="금액 없음")
    _add(client, a, kind="ott", name="금액 0원", monthly_fee=0)
    no_payer = _add(client, a, kind="ott", name="결제자 없음", monthly_fee=5000)
    client.patch(f"/billing/subscriptions/{no_payer['id']}", json={"payer_id": None}, headers=a)
    plan = _plan(client, a)
    states = _states(plan)
    assert (
        states["준비됨"] == "ready"
        and states["금액 없음"] == "no_fee"
        and states["금액 0원"] == "no_fee"
    )
    assert states["결제자 없음"] == "no_payer"
    assert (plan["ready_count"], plan["ready_total"]) == (1, 10000)
    ready = [i for i in plan["items"] if i["name"] == "준비됨"][0]
    assert (ready["date"], ready["payer_name"], ready["split_count"], ready["amount"]) == (
        "2026-10-03",
        "지민",
        3,
        10000,
    )
    assert (
        client.get("/billing/subscriptions/monthly", params={"month": "2026-13"}, headers=a).json()[
            "code"
        ]
        == "invalid_month"
    )


def test_generate_creates_unsettled_expenses_with_payer_split_and_link(client, family):
    a, hdr, ids = _family(client, family)
    ott = _add(client, hdr["수진"], kind="ott", name="넷플릭스", monthly_fee=17000, billing_day=5)
    tel = _add(
        client,
        hdr["엄마"],
        kind="telecom",
        name="통신비",
        carrier="skt",
        monthly_fee=55000,
        billing_day=25,
        split_among=[ids["엄마"]],
    )
    r = _generate(client, a)
    assert r.status_code == 201, r.text
    created = {e["title"]: e for e in r.json()["created"]}
    assert set(created) == {"넷플릭스 구독료", "통신비 구독료"}
    n = created["넷플릭스 구독료"]
    assert (
        n["amount"],
        n["date"],
        n["category"],
        n["paid_by"],
        n["settled"],
        n["subscription_id"],
    ) == (17000, "2026-10-05", "구독", ids["수진"], False, ott["id"])
    assert set(n["split_among"]) == set(ids.values()) and n["target_tag"] == "all"
    t = created["통신비 구독료"]
    assert (t["paid_by"], t["split_among"], t["target_tag"], t["subscription_id"]) == (
        ids["엄마"],
        [ids["엄마"]],
        "custom",
        tel["id"],
    )
    assert (
        _states(r.json()["plan"])["넷플릭스"] == "created" and r.json()["plan"]["ready_count"] == 0
    )
    listed = client.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json()
    assert {e["title"] for e in listed} == {"넷플릭스 구독료", "통신비 구독료"}


def test_generate_is_idempotent_and_can_be_redone_after_deleting_the_expense(client, family):
    a, hdr, ids = _family(client, family)
    _add(client, a, kind="ott", name="왓챠", monthly_fee=7900)
    first = _generate(client, a).json()
    assert len(first["created"]) == 1
    again = _generate(client, a)
    assert again.status_code == 201 and again.json()["created"] == []  # 중복으로 만들지 않는다
    assert len(client.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json()) == 1
    # 만든 지출을 지우면(소프트 삭제) 다시 만들 수 있다
    client.delete(f"/billing/expenses/{first['created'][0]['id']}", headers=a)
    assert _states(_plan(client, a))["왓챠"] == "ready"
    assert len(_generate(client, a).json()["created"]) == 1
    # 다른 달은 따로 만든다
    assert len(_generate(client, a, "2026-11").json()["created"]) == 1
    with SessionLocal() as db:
        rows = list(db.scalars(select(Expense).where(Expense.subscription_id.is_not(None))))
    assert len(rows) == 3  # 10월(삭제됨) + 10월(다시) + 11월


def test_due_date_is_clamped_to_the_length_of_the_month(client, family):
    a, _, _ = family
    _add(client, a, kind="ott", name="말일 결제", monthly_fee=1000, billing_day=31)
    _add(client, a, kind="ott", name="결제일 없음", monthly_fee=1000)
    dates = lambda month: {i["name"]: i["date"] for i in _plan(client, a, month)["items"]}  # noqa: E731
    assert dates("2026-02")["말일 결제"] == "2026-02-28"
    assert dates("2028-02")["말일 결제"] == "2028-02-29"  # 윤년
    assert dates("2026-11")["말일 결제"] == "2026-11-30"
    assert dates("2026-10")["말일 결제"] == "2026-10-31"
    assert dates("2026-10")["결제일 없음"] == "2026-10-01"


def test_skipped_items_are_not_generated_and_deleted_items_are_ignored(client, family):
    a, _, _ = family
    _add(client, a, kind="ott", name="금액 없음")
    gone = _add(client, a, kind="ott", name="지운 항목", monthly_fee=3000)
    client.delete(f"/billing/subscriptions/{gone['id']}", headers=a)
    assert _generate(client, a).json()["created"] == []
    assert "지운 항목" not in _states(_plan(client, a))


def test_generated_expenses_flow_into_the_settlement_only_after_settling(client, family):
    a, hdr, ids = _family(client, family)
    _add(client, hdr["수진"], kind="ott", name="디즈니+", monthly_fee=9000)
    made = _generate(client, a).json()["created"][0]
    s = client.get("/billing/settlement", params={"month": "2026-10"}, headers=a).json()
    assert s["transfers"] == [] and (s["unsettled_count"], s["unsettled_total"]) == (
        1,
        9000,
    )  # 미정산이라 정산에서 제외
    r = client.post(
        "/billing/settlement/tag",
        json={"month": "2026-10", "expense_ids": [made["id"]], "tag": "all"},
        headers=a,
    )
    assert r.status_code == 200
    bal = {b["name"]: b["balance"] for b in r.json()["balances"]}
    assert bal == {"수진": 6000, "지민": -3000, "엄마": -3000} and sum(bal.values()) == 0
    # 월말 알림에도 미정산으로 잡힌다(정산 전)
    other = _add(client, a, kind="ott", name="다음 구독", monthly_fee=1000)
    assert other["payer_id"] == ids["지민"]
    _generate(client, a)
    rem = client.get("/billing/settlement/reminder", params={"on": "2026-10-29"}, headers=a).json()
    assert rem["show"] is True and rem["unsettled_count"] == 1


def test_other_families_do_not_see_or_generate_each_others_items(client, family):
    a, _, _ = family
    _add(client, a, kind="ott", name="우리 구독", monthly_fee=8000)
    outsider = signup(client, "남의 집")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    plan = _plan(client, outsider)
    assert "우리 구독" not in _states(plan)
    assert _generate(client, outsider).json()["created"] == []
    assert (
        client.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json() == []
    )  # 우리 집 지출도 안 생김
