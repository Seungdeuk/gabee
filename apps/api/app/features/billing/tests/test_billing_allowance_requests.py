"""용돈 요청·승인과 월별 요약: 자녀가 요청 -> 부모가 승인(장부 입금)/거절, 자녀 취소, 권한, 최근 6개월 요약."""

from datetime import date

import pytest

from app.features.billing import service
from tests.helpers import signup


def _ids(client, headers) -> dict[str, str]:
    group = client.get("/family-group/groups/me", headers=headers).json()
    return {m["name"]: m["id"] for m in group["members"]}


@pytest.fixture
def today(monkeypatch):
    class Clock:
        value = "2026-10-28"

        def set(self, day: str) -> None:
            self.value = day

    clock = Clock()
    monkeypatch.setattr(service, "today_kst", lambda: clock.value)
    return clock


@pytest.fixture
def home(client, family):
    """지민(그룹을 만든 사람)·수진(자녀)·엄마(부모)."""
    a, b, group = family
    mom = signup(client, "엄마", role="parent")
    client.post("/family-group/groups/join", json={"code": group["invite_code"]}, headers=mom)
    return a, b, mom, _ids(client, a)


def _ledger(client, headers, child_id):
    rows = client.get("/billing/allowances", headers=headers).json()
    return next(r for r in rows if r["child_id"] == child_id)


def _ask(client, headers, child, amount=5000, memo="학용품", expect=201):
    r = client.post(
        f"/billing/allowances/{child}/requests",
        json={"amount": amount, "memo": memo},
        headers=headers,
    )
    assert r.status_code == expect, r.text
    return r.json()


def test_child_requests_and_everyone_sees_it_as_pending(client, home, today):
    a, b, mom, ids = home
    child = ids["수진"]
    data = _ask(client, b, child, 5000, "  학용품  ")
    assert data["can_request"] is True and data["balance"] == 0
    req = data["requests"][0]
    assert (req["amount"], req["memo"], req["status"], req["decided_by_name"]) == (
        5000,
        "학용품",
        "pending",
        "",
    )
    # 부모·다른 가족에게도 보이지만 요청 권한은 본인에게만 있다
    seen = _ledger(client, mom, child)
    assert seen["requests"][0]["id"] == req["id"] and seen["can_request"] is False
    assert _ledger(client, a, child)["can_request"] is False


def test_only_the_child_herself_can_request_and_validation(client, home, today):
    a, b, mom, ids = home
    child = ids["수진"]
    for headers in (mom, a):  # 부모·그룹을 만든 사람이 대신 요청할 수는 없다(바로 지급 기록을 쓴다)
        r = client.post(
            f"/billing/allowances/{child}/requests", json={"amount": 1000}, headers=headers
        )
        assert r.status_code == 403 and r.json()["code"] == "not_allowed"
    for bad in (0, -1, 10_000_001):
        assert (
            client.post(
                f"/billing/allowances/{child}/requests", json={"amount": bad}, headers=b
            ).status_code
            == 422
        )
    too_long = client.post(
        f"/billing/allowances/{child}/requests", json={"amount": 1000, "memo": "x" * 121}, headers=b
    )
    assert too_long.status_code == 422
    assert (
        client.post(
            f"/billing/allowances/{ids['엄마']}/requests", json={"amount": 1000}, headers=mom
        ).status_code
        == 404
    )
    assert _ledger(client, b, child)["requests"] == []  # 실패한 요청은 아무것도 만들지 않는다


def test_pending_requests_are_limited_to_five(client, home, today):
    _, b, _, ids = home
    child = ids["수진"]
    for i in range(5):
        _ask(client, b, child, 1000 + i)
    over = _ask(client, b, child, 9999, expect=400)
    assert over["code"] == "too_many_requests"


def test_approval_posts_a_credit_once_and_can_change_the_amount(client, home, today):
    a, b, mom, ids = home
    child = ids["수진"]
    req = _ask(client, b, child, 5000, "학용품")["requests"][0]
    url = f"/billing/allowances/{child}/requests/{req['id']}/approve"
    done = client.post(url, json={"amount": 3000, "note": "이번엔 3천원만"}, headers=mom)
    assert done.status_code == 200
    data = done.json()
    assert data["balance"] == 3000
    credit = data["entries"][0]
    assert (
        credit["kind"],
        credit["amount"],
        credit["source"],
        credit["by_name"],
        credit["date"],
    ) == (
        "credit",
        3000,
        "request",
        "엄마",
        "2026-10-28",
    )
    assert credit["memo"] == "용돈 요청: 학용품"
    r = data["requests"][0]
    assert (r["status"], r["approved_amount"], r["decided_by_name"], r["decision_note"]) == (
        "approved",
        3000,
        "엄마",
        "이번엔 3천원만",
    )
    again = client.post(url, json={}, headers=a)
    assert again.status_code == 400 and again.json()["code"] == "not_pending"
    assert _ledger(client, a, child)["balance"] == 3000  # 두 번 입금되지 않았다


def test_approval_without_amount_uses_the_requested_amount(client, home, today):
    _, b, mom, ids = home
    child = ids["수진"]
    req = _ask(client, b, child, 7000)["requests"][0]
    data = client.post(
        f"/billing/allowances/{child}/requests/{req['id']}/approve", json={}, headers=mom
    ).json()
    assert data["balance"] == 7000 and data["requests"][0]["approved_amount"] == 7000


def test_only_managers_can_decide_and_unknown_requests_are_404(client, home, today):
    a, b, mom, ids = home
    child = ids["수진"]
    req = _ask(client, b, child)["requests"][0]
    base = f"/billing/allowances/{child}/requests/{req['id']}"
    kid_approve = client.post(f"{base}/approve", json={}, headers=b)  # 자녀가 스스로 승인할 수 없다
    assert kid_approve.status_code == 403 and kid_approve.json()["code"] == "not_allowance_manager"
    kid_reject = client.post(f"{base}/reject", json={}, headers=b)
    assert kid_reject.status_code == 403
    assert _ledger(client, a, child)["balance"] == 0
    assert (
        client.post(
            f"/billing/allowances/{child}/requests/nope/approve", json={}, headers=mom
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/billing/allowances/{child}/requests/nope/reject", json={}, headers=mom
        ).status_code
        == 404
    )


def test_reject_keeps_the_balance_and_blocks_a_later_approval(client, home, today):
    a, b, mom, ids = home
    child = ids["수진"]
    req = _ask(client, b, child)["requests"][0]
    base = f"/billing/allowances/{child}/requests/{req['id']}"
    data = client.post(f"{base}/reject", json={"note": "다음 주에"}, headers=a).json()
    assert data["balance"] == 0 and data["entries"] == []
    r = data["requests"][0]
    assert (r["status"], r["decided_by_name"], r["decision_note"]) == (
        "rejected",
        "지민",
        "다음 주에",
    )
    late = client.post(f"{base}/approve", json={}, headers=mom)
    assert late.status_code == 400 and late.json()["code"] == "not_pending"


def test_child_can_cancel_only_her_own_pending_request(client, home, today):
    a, b, mom, ids = home
    child = ids["수진"]
    req = _ask(client, b, child)["requests"][0]
    base = f"/billing/allowances/{child}/requests/{req['id']}"
    assert (
        client.delete(base, headers=mom).status_code == 403
    )  # 부모는 자녀의 요청을 취소하지 않고 거절한다
    cancelled = client.delete(base, headers=b)
    assert cancelled.status_code == 200 and cancelled.json()["requests"][0]["status"] == "cancelled"
    again = client.delete(base, headers=b)
    assert again.status_code == 400 and again.json()["code"] == "not_pending"
    assert client.post(f"{base}/approve", json={}, headers=mom).json()["code"] == "not_pending"
    # 다른 자녀(지민)의 장부에 있는 요청은 수진이 건드릴 수 없다
    other = _ask(client, a, ids["지민"])["requests"][0]
    other_url = f"/billing/allowances/{ids['지민']}/requests/{other['id']}"
    assert client.delete(other_url, headers=b).status_code == 403


def test_request_list_shows_waiting_first_then_recent_decisions_capped_at_ten(client, home, today):
    _, b, mom, ids = home
    child = ids["수진"]
    for i in range(12):  # 12건을 요청하고 바로 거절한다(대기는 늘 0~1건)
        req = _ask(client, b, child, 1000 + i)["requests"][0]
        client.post(
            f"/billing/allowances/{child}/requests/{req['id']}/reject", json={}, headers=mom
        )
    for i in range(3):
        _ask(client, b, child, 5000 + i)
    got = _ledger(client, b, child)["requests"]
    assert [r["status"] for r in got[:3]] == ["pending"] * 3  # 대기 중인 요청이 먼저
    assert [r["amount"] for r in got[:3]] == [5000, 5001, 5002]  # 대기는 오래된 순
    decided = got[3:]
    assert len(decided) == 10 and {r["status"] for r in decided} == {
        "rejected"
    }  # 처리된 것은 최근 10건
    assert [r["amount"] for r in decided][0] == 1011  # 가장 최근에 낸 것부터


def test_other_families_cannot_touch_requests(client, home, other_family, today):
    _, b, mom, ids = home
    child = ids["수진"]
    req = _ask(client, b, child)["requests"][0]
    base = f"/billing/allowances/{child}/requests/{req['id']}"
    for method, path in (("post", f"{base}/approve"), ("post", f"{base}/reject"), ("delete", base)):
        r = getattr(client, method)(
            path, **({"json": {}} if method == "post" else {}), headers=other_family
        )
        assert r.status_code in (403, 404), (path, r.status_code)
    assert _ledger(client, mom, child)["requests"][0]["status"] == "pending"


def test_monthly_summary_covers_six_months_and_ignores_voided_rows(client, home, today):
    a, b, _, ids = home
    child = ids["수진"]
    today.set("2026-10-28")

    def credit(day, amount):
        r = client.post(
            f"/billing/allowances/{child}/credits", json={"amount": amount, "date": day}, headers=a
        )
        assert r.status_code == 201, r.text
        return r.json()

    credit("2026-10-05", 30000)
    credit("2026-09-05", 20000)
    credit("2026-05-05", 99999)  # 6개월 밖(5월은 10월 기준 6번째 이전)
    credit("2026-06-10", 10000)
    client.post(
        f"/billing/allowances/{child}/uses", json={"amount": 4000, "date": "2026-10-12"}, headers=b
    )
    client.post(
        f"/billing/allowances/{child}/uses", json={"amount": 1500, "date": "2026-09-20"}, headers=b
    )
    wrong = client.post(
        f"/billing/allowances/{child}/uses", json={"amount": 500, "date": "2026-10-13"}, headers=b
    ).json()
    mistake = next(e for e in wrong["entries"] if e["amount"] == 500)
    client.delete(
        f"/billing/allowances/{child}/entries/{mistake['id']}", headers=b
    )  # 취소한 줄은 빠진다
    months = _ledger(client, a, child)["months"]
    assert [m["month"] for m in months] == [
        "2026-10",
        "2026-09",
        "2026-08",
        "2026-07",
        "2026-06",
        "2026-05",
    ]
    by = {m["month"]: (m["credit"], m["use"]) for m in months}
    assert by["2026-10"] == (30000, 4000)
    assert by["2026-09"] == (20000, 1500)
    assert by["2026-08"] == (0, 0) and by["2026-07"] == (0, 0)
    assert by["2026-06"] == (10000, 0)
    assert by["2026-05"] == (99999, 0)  # 최근 6개월에 5월이 포함된다(10, 9, 8, 7, 6, 5)


def test_monthly_summary_crosses_the_year_boundary(client, home, today):
    a, _, _, ids = home
    child = ids["수진"]
    today.set("2027-02-10")
    client.post(
        f"/billing/allowances/{child}/credits",
        json={"amount": 1000, "date": "2026-12-25"},
        headers=a,
    )
    months = _ledger(client, a, child)["months"]
    assert [m["month"] for m in months] == [
        "2027-02",
        "2027-01",
        "2026-12",
        "2026-11",
        "2026-10",
        "2026-09",
    ]
    assert {m["month"]: m["credit"] for m in months}["2026-12"] == 1000
    assert date.fromisoformat(today.value).year == 2027
