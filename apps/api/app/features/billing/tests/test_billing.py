"""공동 지출과 월 정산 계산."""


def test_billing_summary_splits_equally(client, family):
    a, b, _ = family
    for title, amount, h in (("진료비", 30000, a), ("약", 10000, b), ("장보기", 20000, a)):
        r = client.post(
            "/billing/expenses",
            json={"title": title, "amount": amount, "date": "2026-10-12"},
            headers=h,
        )
        assert r.status_code == 201
    client.post(
        "/billing/expenses",
        json={"title": "지난달", "amount": 99999, "date": "2026-09-30"},
        headers=a,
    )
    s = client.get("/billing/summary", params={"month": "2026-10"}, headers=a).json()
    assert (s["total"], s["count"]) == (60000, 3)
    by_name = {x["name"]: x for x in s["balances"]}
    assert by_name["지민"]["paid"] == 50000 and by_name["지민"]["balance"] == 20000  # 받을 돈
    assert by_name["수진"]["paid"] == 10000 and by_name["수진"]["balance"] == -20000  # 낼 돈
    assert sum(x["balance"] for x in s["balances"]) == 0


def test_billing_validation(client, family):
    a, _, _ = family
    assert (
        client.post(
            "/billing/expenses", json={"title": "x", "amount": 0, "date": "2026-10-12"}, headers=a
        ).status_code
        == 422
    )
    assert (
        client.get("/billing/summary", params={"month": "2026-13"}, headers=a).json()["code"]
        == "invalid_month"
    )
