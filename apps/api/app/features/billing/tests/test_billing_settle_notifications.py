"""정산하기가 끝나면 송금할 사람·받을 사람에게 알림함으로 알린다(금액은 알림 문구에 넣지 않는다)."""

MONTH = "2026-10"


def _expense(client, headers, amount=10000):
    r = client.post(
        "/billing/expenses",
        json={"title": "장보기", "amount": amount, "date": "2026-10-12"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _settle(client, headers, expense_id, tag="all", participants=None):
    body = {"month": MONTH, "expense_ids": [expense_id], "tag": tag}
    if participants is not None:
        body["participants"] = participants
    r = client.post("/billing/settlement/tag", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _notes(client, headers):
    r = client.get("/notifications", params={"kind": "billing"}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_payer_is_notified_when_the_other_member_settles(client, family):
    a, b, _ = family  # a=지민(지출을 냄), b=수진(보낼 사람)
    result = _settle(client, a, _expense(client, a))
    assert [(t["from_name"], t["to_name"]) for t in result["transfers"]] == [("수진", "지민")]
    (note,) = _notes(client, b)
    assert (note["kind"], note["event"], note["target_type"], note["target_id"]) == (
        "billing",
        "settlement_pay",
        "settlement",
        MONTH,
    )
    assert note["title"] == "정산이 끝났어요"
    assert note["body"] == f"{MONTH} 정산에서 보낼 돈이 있어요"
    assert _notes(client, a) == []  # 정산한 본인에게는 보내지 않는다


def test_payee_is_notified_when_the_payer_settles(client, family):
    a, b, _ = family
    _settle(client, b, _expense(client, a))  # 수진이 정산하기를 눌렀다
    (note,) = _notes(client, a)  # 받을 사람 지민
    assert note["event"] == "settlement_receive"
    assert note["body"] == f"{MONTH} 정산에서 받을 돈이 있어요"
    assert _notes(client, b) == []


def test_notification_text_has_no_amount(client, family):
    a, b, _ = family
    _settle(client, a, _expense(client, a, 12345))
    (note,) = _notes(client, b)
    text = f"{note['title']} {note['body']}"
    assert not any(s in text for s in ("12,345", "12345", "6,172", "6172", "원"))


def test_nothing_is_sent_when_there_is_nothing_to_send(client, family):
    a, b, _ = family
    me = client.get("/family-group/me", headers=a).json()["id"]
    result = _settle(client, a, _expense(client, a), tag="custom", participants=[me])
    assert result["transfers"] == []
    assert _notes(client, a) == [] and _notes(client, b) == []
