"""앱의 지출 수정(PATCH /billing/expenses/{id}): 에이전트와 같은 규칙. 내가 낸 지출만, 정산하기 전만, 송금 완료가 있는 달은 잠금."""

from .test_billing_agent_write_stage1 import MONTH, _owe_sujin_to_jimin


def _add(client, headers, title="치과", amount=50000, date="2026-10-12"):
    r = client.post(
        "/billing/expenses",
        json={"title": title, "amount": amount, "date": date},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _patch(client, headers, eid, body):
    return client.patch(f"/billing/expenses/{eid}", json=body, headers=headers)


def _row(client, headers, eid, month=MONTH):
    rows = client.get("/billing/expenses", params={"month": month}, headers=headers).json()
    return next((e for e in rows if e["id"] == eid), None)


def _mark_payment(client, headers):
    t = client.get("/billing/settlement", params={"month": MONTH}, headers=headers).json()[
        "transfers"
    ][0]
    r = client.post(
        "/billing/settlement/payments",
        json={
            "month": MONTH,
            "from_user_id": t["from_user_id"],
            "to_user_id": t["to_user_id"],
            "amount": t["amount"],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text


def test_own_unsettled_expense_can_be_edited(client, family):
    a, _, _ = family
    eid = _add(client, a)
    before = _row(client, a, eid)
    r = _patch(
        client,
        a,
        eid,
        {"title": " 치과 검진 ", "amount": 60000, "date": "2026-10-20", "category": "의료"},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["title"], out["amount"], out["date"], out["category"]) == (
        "치과 검진",
        60000,
        "2026-10-20",
        "의료",
    )
    after = _row(client, a, eid)
    # 낸 사람·나눌 사람·정산 상태는 건드리지 않는다
    assert (after["paid_by"], after["split_among"], after["settled"]) == (
        before["paid_by"],
        before["split_among"],
        False,
    )


def test_only_the_fields_sent_change(client, family):
    a, _, _ = family
    eid = _add(client, a)
    r = _patch(client, a, eid, {"amount": 51000})
    assert r.status_code == 200
    out = r.json()
    assert (out["title"], out["amount"], out["date"]) == ("치과", 51000, "2026-10-12")


def test_someone_elses_expense_is_rejected(client, family):
    a, b, _ = family
    eid = _add(client, b, "수진 간식", 3000)
    r = _patch(client, a, eid, {"amount": 4000})  # 지민이 수진의 지출을 고치려 함
    assert r.status_code == 400 and r.json()["code"] == "expense_not_editable"
    assert "내가 낸 지출만" in r.json()["message"]
    assert _row(client, a, eid)["amount"] == 3000


def test_unknown_and_other_family_expenses_are_404(client, family, other_family):
    a, _, _ = family
    foreign = _add(client, other_family, "남의 가족 지출")
    for bad in ("nope", foreign):
        assert _patch(client, a, bad, {"amount": 1}).status_code == 404


def test_settled_expense_is_locked(client, family):
    a, _, _ = family
    eid = _add(client, a, "장보기", 10000)
    client.post(
        "/billing/settlement/tag",
        json={"month": MONTH, "expense_ids": [eid], "tag": "all"},
        headers=a,
    )
    r = _patch(client, a, eid, {"amount": 11000})
    assert r.status_code == 400 and r.json()["code"] == "expense_not_editable"
    assert _row(client, a, eid)["amount"] == 10000


def test_month_with_a_completed_payment_is_locked(client, family):
    a, b, _ = family
    _owe_sujin_to_jimin(client, a, b)
    spare = _add(client, a, "정산 전 지출", 1000)  # 정산하기를 하지 않은 내 지출
    _mark_payment(client, a)
    r = _patch(client, a, spare, {"amount": 2000})
    assert r.status_code == 400 and "송금 완료" in r.json()["message"]
    assert _row(client, a, spare)["amount"] == 1000


def test_moving_to_a_month_with_a_payment_is_rejected_but_same_month_is_fine(client, family):
    a, b, _ = family
    _owe_sujin_to_jimin(client, a, b)
    _mark_payment(client, a)  # 2026-10 에 송금 완료가 있다
    mover = _add(client, a, "9월 지출", 5000, "2026-09-15")
    r = _patch(client, a, mover, {"date": "2026-10-03"})
    assert r.status_code == 400 and "옮기려는 달" in r.json()["message"]
    assert _patch(client, a, mover, {"date": "2026-09-20"}).status_code == 200


def test_nothing_to_change_blank_title_and_empty_body(client, family):
    a, _, _ = family
    eid = _add(client, a)
    same = _patch(client, a, eid, {"title": "치과", "amount": 50000})
    assert same.status_code == 400 and "바뀌는 것이 없어요" in same.json()["message"]
    blank = _patch(client, a, eid, {"title": "   "})
    assert blank.status_code == 400 and "제목" in blank.json()["message"]
    assert _patch(client, a, eid, {}).status_code == 422  # 바꿀 값이 없다


def test_impossible_date_and_amount_are_rejected(client, family):
    a, _, _ = family
    eid = _add(client, a)
    assert _patch(client, a, eid, {"date": "2026-11-31"}).status_code == 422
    assert _patch(client, a, eid, {"amount": 0}).status_code == 422
