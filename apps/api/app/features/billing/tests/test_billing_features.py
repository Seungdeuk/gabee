"""정산(정수 원·나머지·최소 송금), 지출 소프트 삭제, 용돈, 가족 할인 상태."""

from app.features.billing.settlement import minimal_transfers, split_equally
from tests.helpers import signup


def _third(client, group):
    c = signup(client, "민준")
    client.post("/family-group/groups/join", json={"code": group["invite_code"]}, headers=c)
    return c


def _ids(client, headers) -> dict[str, str]:
    group = client.get("/family-group/groups/me", headers=headers).json()
    return {m["name"]: m["id"] for m in group["members"]}


def _expense(client, headers, amount, **extra):
    body = {"title": "장보기", "amount": amount, "date": "2026-10-12", **extra}
    r = client.post("/billing/expenses", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_split_gives_remainder_to_first_people():
    assert split_equally(100, ["a", "b", "c"]) == {"a": 34, "b": 33, "c": 33}
    assert split_equally(101, ["a", "b", "c"]) == {"a": 34, "b": 34, "c": 33}
    assert sum(split_equally(99999, list("abcdefg")).values()) == 99999


def test_minimal_transfers_settles_everything():
    balances = {"a": 50, "b": -20, "c": -30, "d": 0}
    transfers = minimal_transfers(balances)
    assert len(transfers) == 2
    after = dict(balances)
    for f, t, amount in transfers:
        after[f] += amount
        after[t] -= amount
    assert set(after.values()) == {0}


def test_settlement_balances_sum_to_zero_and_payment_flow(client, family):
    a, _, group = family
    c = _third(client, group)
    ids = _ids(client, a)
    _expense(client, a, 10000)  # 3명이 나누면 3334 / 3333 / 3333
    _expense(client, c, 5000, split_among=[ids["지민"], ids["수진"]])
    s = client.get("/billing/settlement", params={"month": "2026-10"}, headers=a).json()
    assert sum(b["balance"] for b in s["balances"]) == 0
    assert sum(b["remaining"] for b in s["balances"]) == 0
    assert all(isinstance(b["balance"], int) for b in s["balances"])
    assert s["transfers"] and s["completed"] == []

    t = s["transfers"][0]
    done = client.post(
        "/billing/settlement/payments",
        json={
            "month": "2026-10",
            "from_user_id": t["from_user_id"],
            "to_user_id": t["to_user_id"],
            "amount": t["amount"],
        },
        headers=a,
    )
    assert done.status_code == 201
    after = done.json()
    assert len(after["completed"]) == 1
    assert sum(b["remaining"] for b in after["balances"]) == 0
    assert len(after["transfers"]) < len(s["transfers"])

    # 목록에 없는 송금은 거절한다
    bad = client.post(
        "/billing/settlement/payments",
        json={
            "month": "2026-10",
            "from_user_id": t["from_user_id"],
            "to_user_id": t["to_user_id"],
            "amount": t["amount"],
        },
        headers=a,
    )
    assert bad.json()["code"] == "unknown_transfer"

    undone = client.delete(f"/billing/settlement/payments/{after['completed'][0]['id']}", headers=a)
    assert undone.json()["completed"] == []


def test_expense_soft_delete_hides_it_and_keeps_row(client, family):
    a, _, _ = family
    e = _expense(client, a, 3000)
    assert e["paid_by_name"] == "지민"
    assert client.delete(f"/billing/expenses/{e['id']}", headers=a).status_code == 204
    assert client.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json() == []
    assert client.delete(f"/billing/expenses/{e['id']}", headers=a).status_code == 404

    from app.features.billing.models import Expense
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        row = db.get(Expense, e["id"])
        assert row is not None and row.deleted_at is not None


def test_expense_rejects_empty_split(client, family):
    a, _, _ = family
    body = {"title": "x", "amount": 1000, "date": "2026-10-12"}
    r = client.post("/billing/expenses", json={**body, "split_among": []}, headers=a)
    assert r.json()["code"] == "empty_split"


def test_allowance_blocks_use_over_remaining(client, family):
    a, _, _ = family
    ids = _ids(client, a)
    child = ids["수진"]
    use = {"amount": 1000, "date": "2026-10-12"}
    no_budget = client.post(f"/billing/allowances/{child}/uses", json=use, headers=a)
    assert no_budget.json()["code"] == "no_budget"

    client.put(f"/billing/allowances/{child}", json={"month": "2026-10", "budget": 5000}, headers=a)
    ok = client.post(f"/billing/allowances/{child}/uses", json={**use, "amount": 3000}, headers=a)
    assert ok.status_code == 201 and ok.json()["remaining"] == 2000
    over = client.post(f"/billing/allowances/{child}/uses", json={**use, "amount": 2001}, headers=a)
    assert over.status_code == 400 and over.json()["code"] == "over_budget"
    exact = client.post(
        f"/billing/allowances/{child}/uses", json={**use, "amount": 2000}, headers=a
    )
    assert exact.json()["remaining"] == 0

    low = client.put(
        f"/billing/allowances/{child}", json={"month": "2026-10", "budget": 4000}, headers=a
    )
    assert low.json()["code"] == "budget_below_used"
    listed = client.get("/billing/allowances", params={"month": "2026-10"}, headers=a).json()
    mine = next(x for x in listed if x["child_id"] == child)
    assert (mine["budget"], mine["used"], mine["remaining"], len(mine["uses"])) == (
        5000,
        5000,
        0,
        2,
    )


def test_subscription_status_change_and_notice(client, family):
    a, _, _ = family
    data = client.get("/billing/subscriptions", headers=a).json()
    assert "예시, 실제 적용은 통신사에서 확인" in data["notice"]
    assert {i["kind"] for i in data["items"]} == {"ott", "telecom"}
    assert {i["status"] for i in data["items"]} == {"check"}
    item = data["items"][0]
    r = client.patch(f"/billing/subscriptions/{item['id']}", json={"status": "active"}, headers=a)
    assert r.json()["status"] == "active"
    bad = client.patch(f"/billing/subscriptions/{item['id']}", json={"status": "free"}, headers=a)
    assert bad.status_code == 422


def test_paid_by_is_always_the_logged_in_user_even_if_the_body_claims_another(client, family):
    a, b, _ = family
    ids = _ids(client, a)
    body = {
        "title": "대신 냈다고 주장",
        "amount": 3000,
        "date": "2026-10-12",
        "paid_by": ids["지민"],
    }
    r = client.post("/billing/expenses", json=body, headers=b)  # 수진이 요청
    assert r.status_code == 201
    assert r.json()["paid_by"] == ids["수진"] and r.json()["paid_by_name"] == "수진"
    s = client.get("/billing/summary", params={"month": "2026-10"}, headers=a).json()
    assert {x["name"]: x["paid"] for x in s["balances"]} == {"지민": 0, "수진": 3000}


def test_expense_request_schema_has_no_paid_by(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["ExpenseCreate"]
    assert "paid_by" not in schema["properties"]
