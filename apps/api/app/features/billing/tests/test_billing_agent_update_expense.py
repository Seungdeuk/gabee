"""정산 에이전트의 지출 수정 제안: 제목·금액·날짜·카테고리만, 내가 낸 것·정산 전·송금 완료 없는 달만. 앱(REST)에는 수정 API 가 없다."""

from .test_billing_agent_write_stage1 import MONTH, _chat, _confirm, _owe_sujin_to_jimin

TOOL = "propose_update_expense"


def _add(client, headers, title="치과", amount=50000, date="2026-10-12"):
    r = client.post(
        "/billing/expenses", json={"title": title, "amount": amount, "date": date}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _rows(client, headers, month=MONTH):
    return client.get("/billing/expenses", params={"month": month}, headers=headers).json()


def _propose(client, headers, monkeypatch, args):
    return _chat(client, headers, monkeypatch, TOOL, args)["proposals"]


def test_own_expense_is_updated_only_after_confirm(client, family, monkeypatch):
    a, _, _ = family
    eid = _add(client, a)
    out = _chat(
        client, a, monkeypatch, TOOL, {"expense_id": eid, "amount": 60000, "title": "치과 검진"}
    )
    assert out["tool_calls"] == [TOOL]
    (p,) = out["proposals"]
    assert p["summary"] == "지출 수정: 치과 — 제목 치과 → 치과 검진, 금액 50,000원 → 60,000원"
    assert [(e["title"], e["amount"]) for e in _rows(client, a)] == [
        ("치과", 50000)
    ]  # 제안만으론 그대로
    assert _confirm(client, a, p["token"]).status_code == 200
    (e,) = _rows(client, a)
    assert (e["title"], e["amount"], e["category"], e["split_among"]) == (
        "치과 검진",
        60000,
        "기타",
        e["split_among"],  # 나눌 사람은 그대로
    )
    assert _confirm(client, a, p["token"]).status_code == 409


def test_split_and_payer_cannot_be_changed(client, family, monkeypatch):
    a, b, _ = family
    eid = _add(client, a)
    before = _rows(client, a)[0]
    (p,) = _propose(
        client,
        a,
        monkeypatch,
        {"expense_id": eid, "amount": 1000, "split_among": ["수진"], "paid_by": "수진"},
    )
    assert "수진" not in p["summary"]
    _confirm(client, a, p["token"])
    after = _rows(client, a)[0]
    assert (after["paid_by"], after["split_among"]) == (before["paid_by"], before["split_among"])


def test_nothing_to_change_or_invalid_values_are_not_proposed(client, family, monkeypatch):
    a, _, _ = family
    eid = _add(client, a)
    for args in (
        {"expense_id": eid},  # 바꿀 값 없음
        {"expense_id": eid, "amount": 50000, "title": "치과"},  # 지금 값과 같음
        {"expense_id": eid, "amount": 0},
        {"expense_id": eid, "amount": -5},
        {"expense_id": eid, "title": "   "},
        {"expense_id": eid, "title": "가" * 121},
        {"expense_id": eid, "date": "어제"},
        {"expense_id": eid, "category": "가" * 17},
    ):
        assert _propose(client, a, monkeypatch, args) == [], args
    assert [(e["title"], e["amount"]) for e in _rows(client, a)] == [("치과", 50000)]


def test_someone_elses_unknown_or_foreign_expense_is_not_proposed(
    client, family, other_family, monkeypatch
):
    a, b, _ = family
    theirs = _add(client, b, "수진 간식", 3000)
    foreign = _add(client, other_family, "남의 가족")
    for eid in (theirs, foreign, "nope"):
        assert _propose(client, a, monkeypatch, {"expense_id": eid, "amount": 1}) == []
    assert [e["amount"] for e in _rows(client, a)] == [3000]


def test_settled_expense_and_locked_month_are_not_proposed(client, family, monkeypatch):
    a, b, _ = family
    settled = _add(client, a, "장보기", 10000)
    client.post(
        "/billing/settlement/tag",
        json={"month": MONTH, "expense_ids": [settled], "tag": "all"},
        headers=a,
    )
    assert _propose(client, a, monkeypatch, {"expense_id": settled, "amount": 1}) == []
    open_one = _add(client, a, "미정산", 2000)
    t = client.get("/billing/settlement", params={"month": MONTH}, headers=a).json()["transfers"][0]
    client.post(
        "/billing/settlement/payments",
        json={
            "month": MONTH,
            "from_user_id": t["from_user_id"],
            "to_user_id": t["to_user_id"],
            "amount": t["amount"],
        },
        headers=a,
    )
    assert _propose(client, a, monkeypatch, {"expense_id": open_one, "amount": 1}) == []


def test_moving_into_a_locked_month_is_not_proposed(client, family, monkeypatch):
    a, b, _ = family
    _owe_sujin_to_jimin(client, a, b)
    t = client.get("/billing/settlement", params={"month": MONTH}, headers=a).json()["transfers"][0]
    client.post(
        "/billing/settlement/payments",
        json={
            "month": MONTH,
            "from_user_id": t["from_user_id"],
            "to_user_id": t["to_user_id"],
            "amount": t["amount"],
        },
        headers=a,
    )  # 10월은 송금 완료 표시가 있어 잠김
    sept = _add(client, a, "9월 지출", 4000, "2026-09-05")
    assert _propose(client, a, monkeypatch, {"expense_id": sept, "date": "2026-10-20"}) == []
    # 잠기지 않은 달 사이의 이동은 된다
    (p,) = _propose(client, a, monkeypatch, {"expense_id": sept, "date": "2026-09-06"})
    assert "날짜 2026-09-05 → 2026-09-06" in p["summary"]
    assert _confirm(client, a, p["token"]).status_code == 200
    assert _rows(client, a, "2026-09")[0]["date"] == "2026-09-06"


def test_update_is_rechecked_at_confirm_time(client, family, monkeypatch):
    a, _, _ = family
    eid = _add(client, a, "장보기", 10000)
    (p,) = _propose(client, a, monkeypatch, {"expense_id": eid, "amount": 20000})
    client.post(  # 제안 뒤에 정산하기가 끝남
        "/billing/settlement/tag",
        json={"month": MONTH, "expense_ids": [eid], "tag": "all"},
        headers=a,
    )
    r = _confirm(client, a, p["token"])
    assert r.status_code == 400 and r.json()["code"] == "expense_not_editable"
    assert _rows(client, a)[0]["amount"] == 10000


def test_update_token_is_not_usable_by_another_member(client, family, monkeypatch):
    a, b, _ = family
    eid = _add(client, a)
    (p,) = _propose(client, a, monkeypatch, {"expense_id": eid, "amount": 1})
    assert _confirm(client, b, p["token"]).json()["code"] == "proposal_invalid"
    assert _rows(client, a)[0]["amount"] == 50000
