"""정산 에이전트의 쓰기 1단계: 송금 완료 표시, 용돈 요청 승인·거절. 제안만 하고 확인해야 실행되며, 권한·대기 상태는 실행 때 다시 본다."""

import pytest

from app.features.billing import service
from app.shared.config import settings
from app.shared.llm import agent, proposals
from tests.ai_consent import enable_ai_for_user
from tests.helpers import join_family, signup

MONTH = "2026-10"


def _llm(name, args):
    calls = []

    def fake(body):
        if "가계(정산) 담당" not in body["system"]:
            return {"content": [{"type": "text", "text": "메인"}]}
        calls.append(1)
        if len(calls) == 1:
            return {"content": [{"type": "tool_use", "id": "t1", "name": name, "input": args}]}
        return {"content": [{"type": "text", "text": "확인 버튼을 눌러 주세요."}]}

    return fake


def _chat(client, headers, monkeypatch, name, args, message="해줘"):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", _llm(name, args))
    enable_ai_for_user()
    proposals.reset()
    r = client.post("/billing/agent/chat", json={"message": message}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _confirm(client, headers, token):
    return client.post("/billing/agent/confirm", json={"token": token}, headers=headers)


@pytest.fixture
def today(monkeypatch):
    monkeypatch.setattr(service, "today_kst", lambda: "2026-10-28")


@pytest.fixture
def home(client, family):
    """지민(그룹을 만든 사람)·수진(자녀)·엄마(부모)."""
    a, b, group = family
    mom = signup(client, "엄마", role="parent")
    join_family(client, a, group["invite_code"], mom)
    members = client.get("/family-group/groups/me", headers=a).json()["members"]
    return a, b, mom, {m["name"]: m["id"] for m in members}


# ---- 송금 완료 표시 ----


def _owe_sujin_to_jimin(client, a, b):
    """지민이 낸 지출을 둘이 나눠 '수진 → 지민' 송금이 하나 생기게 한다(수진 몫 5,000원)."""
    e = client.post(
        "/billing/expenses",
        json={"title": "장보기", "amount": 10000, "date": "2026-10-12"},
        headers=a,
    ).json()
    r = client.post(
        "/billing/settlement/tag",
        json={"month": MONTH, "expense_ids": [e["id"]], "tag": "all"},
        headers=a,
    )
    assert r.status_code == 200, r.text
    (t,) = r.json()["transfers"]
    assert (t["from_name"], t["to_name"], t["amount"]) == ("수진", "지민", 5000)


def _payments(client, headers):
    return client.get("/billing/settlement", params={"month": MONTH}, headers=headers).json()


PAID = {"month": MONTH, "from_name": "수진", "to_name": "지민"}


def test_mark_paid_is_only_proposed_until_confirmed(client, family, monkeypatch, today):
    a, b, _ = family
    _owe_sujin_to_jimin(client, a, b)
    out = _chat(client, a, monkeypatch, "propose_mark_paid", PAID)
    assert out["tool_calls"] == ["propose_mark_paid"]
    (p,) = out["proposals"]
    assert p["summary"] == "송금 완료 표시: 수진 → 지민 5,000원 (2026-10)"
    assert _payments(client, a)["completed"] == []  # 제안만으로는 표시되지 않는다
    assert _confirm(client, a, p["token"]).status_code == 200
    done = _payments(client, a)
    assert len(done["completed"]) == 1 and done["transfers"] == []
    assert _confirm(client, a, p["token"]).status_code == 409  # 한 번만


def test_mark_paid_ignores_an_amount_from_the_llm_and_rejects_unlisted_transfers(
    client, family, monkeypatch, today
):
    a, b, _ = family
    _owe_sujin_to_jimin(client, a, b)
    # 금액을 줘도 쓰지 않는다(스키마에 없는 값). 서버가 송금 목록의 5,000원을 쓴다
    (p,) = _chat(client, a, monkeypatch, "propose_mark_paid", {**PAID, "amount": 999999})[
        "proposals"
    ]
    assert "5,000원" in p["summary"]
    # 목록에 없는 방향·이름·달은 제안이 만들어지지 않는다
    for bad in (
        {**PAID, "from_name": "지민", "to_name": "수진"},
        {**PAID, "from_name": "없는사람"},
        {**PAID, "month": "2026-09"},
        {**PAID, "month": "2026-13"},
    ):
        assert _chat(client, a, monkeypatch, "propose_mark_paid", bad)["proposals"] == []
    assert _payments(client, a)["completed"] == []


def test_mark_paid_rechecks_the_transfer_at_confirm_time(client, family, monkeypatch, today):
    a, b, _ = family
    _owe_sujin_to_jimin(client, a, b)
    (p,) = _chat(client, a, monkeypatch, "propose_mark_paid", PAID)["proposals"]
    # 제안 뒤에 앱에서 같은 송금을 먼저 완료로 표시하면, 확인은 실패하고 두 번 표시되지 않는다
    t = _payments(client, a)["transfers"][0]
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
    r = _confirm(client, a, p["token"])
    assert r.status_code == 400 and r.json()["code"] == "unknown_transfer"
    assert len(_payments(client, a)["completed"]) == 1


def test_mark_paid_token_is_not_usable_by_another_member(client, family, monkeypatch, today):
    a, b, _ = family
    _owe_sujin_to_jimin(client, a, b)
    (p,) = _chat(client, a, monkeypatch, "propose_mark_paid", PAID)["proposals"]
    assert _confirm(client, b, p["token"]).json()["code"] == "proposal_invalid"
    assert _payments(client, a)["completed"] == []


# ---- 용돈 요청 승인·거절 ----


def _request(client, b, ids, amount=5000, memo="학용품"):
    r = client.post(
        f"/billing/allowances/{ids['수진']}/requests",
        json={"amount": amount, "memo": memo},
        headers=b,
    )
    assert r.status_code == 201, r.text
    return r.json()["requests"][0]["id"]


def _ledger(client, headers, ids):
    rows = client.get("/billing/allowances", headers=headers).json()
    return next(r for r in rows if r["child_id"] == ids["수진"])


def _decide(request_id, decision, **extra):
    return {"child_name": "수진", "request_id": request_id, "decision": decision, **extra}


def test_approval_is_only_proposed_until_confirmed_and_posts_one_credit(
    client, home, monkeypatch, today
):
    a, b, mom, ids = home
    rid = _request(client, b, ids)
    (p,) = _chat(
        client, mom, monkeypatch, "propose_decide_allowance_request", _decide(rid, "approve")
    )["proposals"]
    assert p["summary"] == "용돈 요청 승인: 수진 5,000원"
    assert _ledger(client, mom, ids)["balance"] == 0  # 제안만으로는 입금되지 않는다
    assert _confirm(client, mom, p["token"]).status_code == 200
    ledger = _ledger(client, mom, ids)
    assert ledger["balance"] == 5000 and ledger["requests"][0]["status"] == "approved"
    assert _confirm(client, mom, p["token"]).status_code == 409
    assert _ledger(client, mom, ids)["balance"] == 5000  # 한 번만 입금된다


def test_approval_amount_is_applied_only_when_given_and_shown_in_the_summary(
    client, home, monkeypatch, today
):
    a, b, mom, ids = home
    rid = _request(client, b, ids, 5000)
    out = _chat(
        client,
        a,  # 그룹을 만든 사람도 처리할 수 있다
        monkeypatch,
        "propose_decide_allowance_request",
        _decide(rid, "approve", amount=3000, note="절반만"),
    )
    (p,) = out["proposals"]
    assert p["summary"] == "용돈 요청 승인: 수진 3,000원 (요청 5,000원)"
    assert _confirm(client, a, p["token"]).status_code == 200
    assert _ledger(client, a, ids)["balance"] == 3000
    # 0·음수·너무 큰 금액은 제안으로 이어지지 않는다
    rid2 = _request(client, b, ids, 1000)
    for bad in (0, -5, 10_000_001):
        out = _chat(
            client,
            a,
            monkeypatch,
            "propose_decide_allowance_request",
            _decide(rid2, "approve", amount=bad),
        )
        assert out["proposals"] == []


def test_rejection_leaves_the_balance_alone(client, home, monkeypatch, today):
    a, b, mom, ids = home
    rid = _request(client, b, ids)
    (p,) = _chat(
        client,
        mom,
        monkeypatch,
        "propose_decide_allowance_request",
        _decide(rid, "reject", note="이번 달은 어려워"),
    )["proposals"]
    assert p["summary"] == "용돈 요청 거절: 수진 5,000원"
    assert _confirm(client, mom, p["token"]).status_code == 200
    ledger = _ledger(client, mom, ids)
    assert ledger["balance"] == 0 and ledger["requests"][0]["status"] == "rejected"


def test_only_managers_can_get_a_decision_proposed(client, home, monkeypatch, today):
    a, b, mom, ids = home
    rid = _request(client, b, ids)
    # 자녀(수진)는 자기 요청이라도 승인을 제안할 수 없다
    out = _chat(client, b, monkeypatch, "propose_decide_allowance_request", _decide(rid, "approve"))
    assert out["proposals"] == []
    assert _ledger(client, mom, ids)["balance"] == 0
    assert _ledger(client, mom, ids)["requests"][0]["status"] == "pending"


def test_decisions_reject_unknown_decided_and_foreign_requests(client, home, monkeypatch, today):
    a, b, mom, ids = home
    rid = _request(client, b, ids)
    for bad in (
        _decide("nope", "approve"),
        _decide(rid, "delete"),
        {**_decide(rid, "approve"), "child_name": "없는아이"},
    ):
        out = _chat(client, mom, monkeypatch, "propose_decide_allowance_request", bad)
        assert out["proposals"] == []
    # 다른 가족의 관리자는 이 요청을 볼 수도 없다
    outsider = signup(client, "남", role="parent")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    enable_ai_for_user("남")  # 다른 가족도 AI 를 켠 상태에서, 그래도 이 가족의 요청은 못 본다
    out = _chat(
        client, outsider, monkeypatch, "propose_decide_allowance_request", _decide(rid, "approve")
    )
    assert out["proposals"] == []
    assert _ledger(client, mom, ids)["requests"][0]["status"] == "pending"


def test_decision_is_rechecked_at_confirm_time(client, home, monkeypatch, today):
    a, b, mom, ids = home
    rid = _request(client, b, ids)
    (p,) = _chat(
        client, mom, monkeypatch, "propose_decide_allowance_request", _decide(rid, "approve")
    )["proposals"]
    # 제안 뒤에 다른 관리자가 먼저 거절하면, 확인은 실패하고 입금되지 않는다
    r = client.post(f"/billing/allowances/{ids['수진']}/requests/{rid}/reject", json={}, headers=a)
    assert r.status_code == 200, r.text
    bad = _confirm(client, mom, p["token"])
    assert bad.status_code == 400 and bad.json()["code"] == "not_pending"
    assert _ledger(client, mom, ids)["balance"] == 0
    # 승인 한 번과 거절 한 번이 같은 요청에 겹쳐도 한쪽만 남는다(같은 답변에서 마지막 제안이 앞선 것을 대신한다)


def test_a_reject_proposal_replaces_an_approve_proposal_for_the_same_request(
    client, home, monkeypatch, today
):
    a, b, mom, ids = home
    rid = _request(client, b, ids)
    calls = []

    def fake(body):
        if "가계(정산) 담당" not in body["system"]:
            return {"content": [{"type": "text", "text": "메인"}]}
        calls.append(1)
        if len(calls) <= 2:
            decision = "approve" if len(calls) == 1 else "reject"
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"t{len(calls)}",
                        "name": "propose_decide_allowance_request",
                        "input": _decide(rid, decision),
                    }
                ]
            }
        return {"content": [{"type": "text", "text": "확인 버튼을 눌러 주세요."}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agent, "_post", fake)
    enable_ai_for_user()
    proposals.reset()
    out = client.post("/billing/agent/chat", json={"message": "처리"}, headers=mom).json()
    (p,) = out["proposals"]
    assert p["summary"].startswith("용돈 요청 거절")
