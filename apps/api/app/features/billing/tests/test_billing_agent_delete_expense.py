"""정산 에이전트의 지출 삭제 제안: 내가 낸 지출만, 정산하기 전만, 송금 완료 표시가 없는 달만. 앱 화면의 삭제보다 엄격하다."""

from .test_billing_agent_write_stage1 import MONTH, _chat, _confirm, _owe_sujin_to_jimin

TOOL = "propose_delete_expense"


def _add(client, headers, title="치과", amount=50000):
    r = client.post(
        "/billing/expenses",
        json={"title": title, "amount": amount, "date": "2026-10-12"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _titles(client, headers):
    rows = client.get("/billing/expenses", params={"month": MONTH}, headers=headers).json()
    return [e["title"] for e in rows]


def test_own_unsettled_expense_is_deleted_only_after_confirm(client, family, monkeypatch):
    a, _, _ = family
    eid = _add(client, a)
    out = _chat(client, a, monkeypatch, TOOL, {"expense_id": eid})
    assert out["tool_calls"] == [TOOL]
    (p,) = out["proposals"]
    assert p["summary"] == "지출 삭제: 치과 50,000원 (2026-10-12)"
    assert _titles(client, a) == ["치과"]  # 제안만으로는 지워지지 않는다
    assert _confirm(client, a, p["token"]).status_code == 200
    assert _titles(client, a) == []
    assert _confirm(client, a, p["token"]).status_code == 409  # 한 번만


def test_someone_elses_expense_is_not_proposed(client, family, monkeypatch):
    a, b, _ = family
    eid = _add(client, b, "수진 간식", 3000)
    out = _chat(client, a, monkeypatch, TOOL, {"expense_id": eid})  # 지민이 수진의 지출을 지우려 함
    assert out["proposals"] == []
    assert _titles(client, a) == ["수진 간식"]


def test_unknown_or_other_family_expense_is_not_proposed(client, family, other_family, monkeypatch):
    a, _, _ = family
    foreign = _add(client, other_family, "남의 가족 지출")
    for bad in ("nope", foreign, ""):
        assert _chat(client, a, monkeypatch, TOOL, {"expense_id": bad})["proposals"] == []
    assert _titles(client, other_family) == ["남의 가족 지출"]  # 다른 가족의 지출은 그대로다


def test_settled_expense_is_not_proposed(client, family, monkeypatch):
    a, b, _ = family
    eid = _add(client, a, "장보기", 10000)
    client.post(
        "/billing/settlement/tag",
        json={"month": MONTH, "expense_ids": [eid], "tag": "all"},
        headers=a,
    )
    assert _chat(client, a, monkeypatch, TOOL, {"expense_id": eid})["proposals"] == []
    assert _titles(client, a) == ["장보기"]


def test_month_with_a_completed_payment_is_locked_for_deletes(client, family, monkeypatch):
    a, b, _ = family
    _owe_sujin_to_jimin(client, a, b)
    spare = _add(client, a, "정산 전 지출", 1000)  # 정산하기를 하지 않은 내 지출
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
    assert _chat(client, a, monkeypatch, TOOL, {"expense_id": spare})["proposals"] == []
    assert "정산 전 지출" in _titles(client, a)


def test_delete_is_rechecked_at_confirm_time(client, family, monkeypatch):
    a, b, _ = family
    eid = _add(client, a, "장보기", 10000)
    (p,) = _chat(client, a, monkeypatch, TOOL, {"expense_id": eid})["proposals"]
    # 제안 뒤에 정산하기가 끝나면, 확인은 실패하고 지출은 남는다
    client.post(
        "/billing/settlement/tag",
        json={"month": MONTH, "expense_ids": [eid], "tag": "all"},
        headers=a,
    )
    r = _confirm(client, a, p["token"])
    assert r.status_code == 400 and r.json()["code"] == "expense_not_deletable"
    assert _titles(client, a) == ["장보기"]


def test_delete_token_cannot_be_used_by_another_member(client, family, monkeypatch):
    a, b, _ = family
    eid = _add(client, a)
    (p,) = _chat(client, a, monkeypatch, TOOL, {"expense_id": eid})["proposals"]
    assert _confirm(client, b, p["token"]).json()["code"] == "proposal_invalid"
    assert _titles(client, a) == ["치과"]
