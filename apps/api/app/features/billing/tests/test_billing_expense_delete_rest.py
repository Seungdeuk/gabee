"""앱의 지출 삭제(DELETE /billing/expenses/{id}): 수정·에이전트와 같은 규칙. 내가 낸 지출만, 정산하기 전만, 송금 완료가 있는 달은 잠금."""

from .test_billing_agent_write_stage1 import MONTH, _owe_sujin_to_jimin
from .test_billing_expense_update_rest import _add, _mark_payment, _row


def _delete(client, headers, eid):
    return client.delete(f"/billing/expenses/{eid}", headers=headers)


def test_own_unsettled_expense_is_deleted(client, family):
    a, _, _ = family
    eid = _add(client, a)
    assert _delete(client, a, eid).status_code == 204
    assert _row(client, a, eid) is None
    assert _delete(client, a, eid).status_code == 404  # 이미 지운 것


def test_someone_elses_expense_is_rejected(client, family):
    a, b, _ = family
    eid = _add(client, b, "수진 간식", 3000)
    r = _delete(client, a, eid)  # 지민이 수진의 지출을 지우려 함
    assert r.status_code == 400 and r.json()["code"] == "expense_not_deletable"
    assert "내가 낸 지출만" in r.json()["message"]
    assert _row(client, a, eid) is not None


def test_unknown_and_other_family_expenses_are_404(client, family, other_family):
    a, _, _ = family
    foreign = _add(client, other_family, "남의 가족 지출")
    for bad in ("nope", foreign):
        assert _delete(client, a, bad).status_code == 404
    assert _row(client, other_family, foreign) is not None  # 다른 가족의 지출은 그대로다


def test_settled_expense_is_locked(client, family):
    a, _, _ = family
    eid = _add(client, a, "장보기", 10000)
    client.post(
        "/billing/settlement/tag",
        json={"month": MONTH, "expense_ids": [eid], "tag": "all"},
        headers=a,
    )
    r = _delete(client, a, eid)
    assert r.status_code == 400 and r.json()["code"] == "expense_not_deletable"
    assert _row(client, a, eid) is not None


def test_month_with_a_completed_payment_is_locked(client, family):
    a, b, _ = family
    _owe_sujin_to_jimin(client, a, b)
    spare = _add(client, a, "정산 전 지출", 1000)  # 정산하기를 하지 않은 내 지출
    _mark_payment(client, a)
    r = _delete(client, a, spare)
    assert r.status_code == 400 and "송금 완료" in r.json()["message"]
    assert _row(client, a, spare) is not None
