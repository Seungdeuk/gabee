"""용돈 장부: 고정 주기(자동 지급/리마인드), 앱 안 입금·사용 내역과 잔액, 권한, 취소. 은행·계좌 연동은 없다."""

from datetime import date

import pytest

from app.features.billing import service
from app.features.billing.allowance import MAX_CATCH_UP, due_dates, next_due
from tests.helpers import signup


def _ids(client, headers) -> dict[str, str]:
    group = client.get("/family-group/groups/me", headers=headers).json()
    return {m["name"]: m["id"] for m in group["members"]}


@pytest.fixture
def today(monkeypatch):
    """서버가 보는 '오늘'(한국 시간)을 바꿀 수 있게 한다. today.set("2026-10-28")."""

    class Clock:
        value = "2026-10-28"  # 수요일

        def set(self, day: str) -> None:
            self.value = day

    clock = Clock()
    monkeypatch.setattr(service, "today_kst", lambda: clock.value)
    return clock


@pytest.fixture
def home(client, family):
    """지민(그룹을 만든 사람)·수진(자녀)·엄마(부모). (지민 헤더, 수진 헤더, 엄마 헤더, id 들)"""
    a, b, group = family
    mom = signup(client, "엄마", role="parent")
    client.post("/family-group/groups/join", json={"code": group["invite_code"]}, headers=mom)
    return a, b, mom, _ids(client, a)


def _ledger(client, headers, child_id):
    rows = client.get("/billing/allowances", headers=headers).json()
    return next(r for r in rows if r["child_id"] == child_id)


def _plan(cycle="monthly", day=25, amount=30000, mode="auto"):
    return {"cycle": cycle, "day": day, "amount": amount, "mode": mode}


# ---------- 지급일 계산(순수 함수) ----------
def test_weekly_due_dates_start_on_the_first_matching_weekday():
    # 2026-10-28 은 수요일(2). 금요일(4) 주기는 10-30, 11-06, ...
    out = due_dates("weekly", 4, date(2026, 10, 28), date(2026, 11, 14))
    assert [d.isoformat() for d in out] == ["2026-10-30", "2026-11-06", "2026-11-13"]
    assert due_dates("weekly", 2, date(2026, 10, 28), date(2026, 10, 28)) == [date(2026, 10, 28)]
    assert due_dates("weekly", 4, date(2026, 10, 28), date(2026, 10, 29)) == []


def test_monthly_due_dates_use_the_last_day_when_the_day_does_not_exist():
    out = due_dates("monthly", 31, date(2026, 1, 1), date(2026, 4, 30))
    assert [d.isoformat() for d in out] == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]
    # 시작일 이전의 그 달 지급일은 세지 않는다
    assert [
        d.isoformat() for d in due_dates("monthly", 5, date(2026, 10, 10), date(2026, 12, 31))
    ] == [
        "2026-11-05",
        "2026-12-05",
    ]


def test_catch_up_is_capped_and_keeps_the_most_recent_dates():
    out = due_dates("weekly", 0, date(2020, 1, 1), date(2026, 10, 28))
    assert len(out) == MAX_CATCH_UP and out[-1] <= date(2026, 10, 28)


def test_next_due_includes_today_and_rolls_over_the_month():
    assert next_due("monthly", 28, date(2026, 10, 28)) == date(2026, 10, 28)
    assert next_due("monthly", 5, date(2026, 10, 28)) == date(2026, 11, 5)
    assert next_due("monthly", 5, date(2026, 12, 28)) == date(2027, 1, 5)
    assert next_due("weekly", 4, date(2026, 10, 28)) == date(2026, 10, 30)


# ---------- 장부: 입금·사용·잔액 ----------
def test_ledger_starts_empty_and_tracks_credit_use_and_running_balance(client, home, today):
    a, _, _, ids = home
    child = ids["수진"]
    start = _ledger(client, a, child)
    assert (start["balance"], start["entries"], start["plan"]) == (0, [], None)

    c = client.post(
        f"/billing/allowances/{child}/credits",
        json={"amount": 10000, "memo": "이번 달 용돈"},
        headers=a,
    )
    assert c.status_code == 201 and c.json()["balance"] == 10000
    u = client.post(
        f"/billing/allowances/{child}/uses", json={"amount": 3500, "memo": "간식"}, headers=a
    )
    data = u.json()
    assert (data["balance"], data["total_credit"], data["total_use"]) == (6500, 10000, 3500)
    newest, oldest = data["entries"]  # 최신순
    assert (newest["kind"], newest["balance_after"], newest["memo"]) == ("use", 6500, "간식")
    assert (oldest["kind"], oldest["balance_after"], oldest["by_name"]) == ("credit", 10000, "지민")


def test_use_cannot_exceed_the_balance_but_exact_balance_is_allowed(client, home, today):
    a, _, _, ids = home
    child = ids["수진"]
    use = {"amount": 1}
    assert (
        client.post(f"/billing/allowances/{child}/uses", json=use, headers=a).json()["code"]
        == "over_balance"
    )  # 아직 입금이 없다
    client.post(f"/billing/allowances/{child}/credits", json={"amount": 5000}, headers=a)
    over = client.post(f"/billing/allowances/{child}/uses", json={"amount": 5001}, headers=a)
    assert over.status_code == 400 and over.json()["code"] == "over_balance"
    exact = client.post(f"/billing/allowances/{child}/uses", json={"amount": 5000}, headers=a)
    assert exact.status_code == 201 and exact.json()["balance"] == 0


def test_amount_and_date_validation(client, home, today):
    a, _, _, ids = home
    child = ids["수진"]
    for bad in (0, -5, 10_000_001):
        r = client.post(f"/billing/allowances/{child}/credits", json={"amount": bad}, headers=a)
        assert r.status_code == 422
    future = client.post(
        f"/billing/allowances/{child}/credits",
        json={"amount": 1000, "date": "2026-10-29"},
        headers=a,
    )
    assert future.status_code == 400 and future.json()["code"] == "future_date"
    past = client.post(
        f"/billing/allowances/{child}/credits",
        json={"amount": 1000, "date": "2026-10-01"},
        headers=a,
    )
    assert past.status_code == 201 and past.json()["entries"][0]["date"] == "2026-10-01"


def test_parents_are_not_children_and_unknown_ids_are_404(client, home, today):
    a, _, mom, ids = home
    names = [r["name"] for r in client.get("/billing/allowances", headers=a).json()]
    assert names == ["지민", "수진"]  # 부모(엄마)는 용돈 대상이 아니다
    for child in (ids["엄마"], "nobody"):
        r = client.post(f"/billing/allowances/{child}/credits", json={"amount": 1000}, headers=a)
        assert r.status_code == 404


# ---------- 권한 ----------
def test_only_parents_or_the_group_owner_manage_but_children_record_their_own_use(
    client, home, today
):
    a, b, mom, ids = home  # a=지민(그룹을 만든 사람), b=수진(자녀), mom=엄마(부모)
    child = ids["수진"]
    # 수진은 자기 용돈 주기·입금·남의 장부를 바꿀 수 없다
    assert (
        client.put(f"/billing/allowances/{child}/plan", json=_plan(), headers=b).json()["code"]
        == "not_allowance_manager"
    )
    r = client.post(f"/billing/allowances/{child}/credits", json={"amount": 5000}, headers=b)
    assert r.status_code == 403 and r.json()["code"] == "not_allowance_manager"
    # 엄마(부모)는 입금할 수 있다
    assert (
        client.post(
            f"/billing/allowances/{child}/credits", json={"amount": 5000}, headers=mom
        ).status_code
        == 201
    )
    # 수진은 자기 사용은 기록할 수 있고, 지민의 장부에는 못 쓴다
    mine = client.post(f"/billing/allowances/{child}/uses", json={"amount": 1000}, headers=b)
    assert mine.status_code == 201 and mine.json()["can_record_use"] is True
    assert mine.json()["can_manage"] is False
    other = client.post(f"/billing/allowances/{ids['지민']}/uses", json={"amount": 1}, headers=b)
    assert other.status_code == 403 and other.json()["code"] == "not_allowed"
    # 구성원은 모두 서로의 잔액·내역을 볼 수 있다(투명성)
    assert _ledger(client, b, child)["balance"] == 4000
    assert _ledger(client, mom, child)["entries"][0]["by_name"] == "수진"


def test_other_families_cannot_see_or_change_the_ledger(client, home, other_family, today):
    a, _, _, ids = home
    child = ids["수진"]
    client.post(f"/billing/allowances/{child}/credits", json={"amount": 5000}, headers=a)
    theirs = client.get("/billing/allowances", headers=other_family).json()
    assert [(r["name"], r["balance"], r["entries"]) for r in theirs] == [("남", 0, [])]
    for method, path, body in (
        ("post", f"/billing/allowances/{child}/credits", {"amount": 1}),
        ("post", f"/billing/allowances/{child}/uses", {"amount": 1}),
        ("put", f"/billing/allowances/{child}/plan", _plan()),
    ):
        r = getattr(client, method)(path, json=body, headers=other_family)
        assert r.status_code in (403, 404), (path, r.status_code)


# ---------- 고정 주기: 자동 지급 ----------
def test_plan_validation(client, home, today):
    a, _, _, ids = home
    child = ids["수진"]
    url = f"/billing/allowances/{child}/plan"
    assert client.put(url, json=_plan("weekly", 7), headers=a).json()["code"] == "invalid_day"
    assert client.put(url, json=_plan("monthly", 0), headers=a).json()["code"] == "invalid_day"
    assert client.put(url, json=_plan("monthly", 32), headers=a).status_code == 422
    assert client.put(url, json=_plan(amount=0), headers=a).status_code == 422
    assert client.put(url, json=_plan(cycle="daily"), headers=a).status_code == 422
    assert client.put(url, json=_plan(mode="manual"), headers=a).status_code == 422
    assert _ledger(client, a, child)["plan"] is None  # 실패한 요청은 아무것도 만들지 않는다


def test_auto_plan_posts_missed_due_dates_once_when_the_ledger_is_opened(client, home, today):
    a, _, _, ids = home
    child = ids["수진"]
    today.set("2026-08-31")
    saved = client.put(
        f"/billing/allowances/{child}/plan", json=_plan("monthly", 25, 30000, "auto"), headers=a
    ).json()
    assert saved["plan"]["next_due"] == "2026-09-25" and saved["balance"] == 0  # 소급하지 않는다

    today.set("2026-10-28")  # 9/25, 10/25 두 번을 지나쳤다
    first = _ledger(client, a, child)
    assert first["balance"] == 60000 and len(first["entries"]) == 2
    assert {e["source"] for e in first["entries"]} == {"plan_auto"}
    assert {e["by_name"] for e in first["entries"]} == {"자동 지급"}
    assert [e["date"] for e in first["entries"]] == ["2026-10-25", "2026-09-25"]
    for _ in range(3):  # 여러 번 열어도 같은 지급일은 다시 만들지 않는다
        again = _ledger(client, a, child)
        assert again["balance"] == 60000 and len(again["entries"]) == 2
    assert first["pending"] == []  # 자동 방식은 알림이 없다
    assert first["plan"]["next_due"] == "2026-11-25"


def test_changing_the_plan_restarts_from_today_and_deleting_keeps_the_ledger(client, home, today):
    a, _, _, ids = home
    child = ids["수진"]
    url = f"/billing/allowances/{child}/plan"
    today.set("2026-08-01")
    client.put(url, json=_plan("monthly", 5, 20000, "auto"), headers=a)
    today.set("2026-10-10")  # 8/5, 9/5, 10/5 세 번
    assert _ledger(client, a, child)["balance"] == 60000

    # 금액·주기를 바꾸면 오늘부터 새 주기로 센다: 이미 쌓인 내역은 그대로, 지난 날짜는 만들지 않는다
    changed = client.put(url, json=_plan("monthly", 5, 50000, "auto"), headers=a).json()
    assert changed["balance"] == 60000 and changed["plan"]["start_date"] == "2026-10-10"
    assert changed["plan"]["next_due"] == "2026-11-05"
    today.set("2026-11-06")
    assert _ledger(client, a, child)["balance"] == 110000  # 11/5 에 5만원이 추가됐다

    gone = client.delete(url, headers=a).json()
    assert gone["plan"] is None and gone["balance"] == 110000 and len(gone["entries"]) == 4
    assert client.delete(url, headers=a).status_code == 404  # 이미 없다


def test_remind_plan_shows_pending_dates_only_to_managers_until_marked_paid(client, home, today):
    a, b, mom, ids = home
    child = ids["수진"]
    today.set("2026-10-01")
    client.put(
        f"/billing/allowances/{child}/plan", json=_plan("weekly", 4, 8000, "remind"), headers=mom
    )
    today.set("2026-10-17")  # 금요일 10/2, 10/9, 10/16 을 지났다
    mine = _ledger(client, mom, child)
    assert [p["due_date"] for p in mine["pending"]] == ["2026-10-02", "2026-10-09", "2026-10-16"]
    assert mine["balance"] == 0  # 리마인드는 눌러야 기록된다
    assert _ledger(client, b, child)["pending"] == []  # 자녀에게는 지급 알림이 보이지 않는다

    paid = client.post(
        f"/billing/allowances/{child}/plan/pay", json={"due_date": "2026-10-09"}, headers=mom
    )
    assert paid.status_code == 201 and paid.json()["balance"] == 8000
    entry = paid.json()["entries"][0]
    assert (entry["source"], entry["by_name"], entry["date"]) == (
        "plan_remind",
        "엄마",
        "2026-10-09",
    )
    assert [p["due_date"] for p in paid.json()["pending"]] == ["2026-10-02", "2026-10-16"]

    again = client.post(
        f"/billing/allowances/{child}/plan/pay", json={"due_date": "2026-10-09"}, headers=mom
    )
    assert again.status_code == 400 and again.json()["code"] == "already_paid"
    wrong = client.post(
        f"/billing/allowances/{child}/plan/pay", json={"due_date": "2026-10-10"}, headers=mom
    )
    assert wrong.json()["code"] == "invalid_due"  # 지급일이 아닌 날짜
    kid = client.post(
        f"/billing/allowances/{child}/plan/pay", json={"due_date": "2026-10-02"}, headers=b
    )
    assert kid.status_code == 403  # 자녀가 스스로 지급 처리할 수 없다


def test_pay_requires_a_remind_plan(client, home, today):
    a, _, _, ids = home
    child = ids["수진"]
    body = {"due_date": "2026-10-28"}
    assert (
        client.post(f"/billing/allowances/{child}/plan/pay", json=body, headers=a).json()["code"]
        == "not_remind"
    )  # 주기가 없다
    client.put(
        f"/billing/allowances/{child}/plan", json=_plan("weekly", 2, 1000, "auto"), headers=a
    )
    assert (
        client.post(f"/billing/allowances/{child}/plan/pay", json=body, headers=a).json()["code"]
        == "not_remind"
    )


# ---------- 취소(지우지 않고 표시) ----------
def test_void_keeps_the_row_and_restores_the_balance(client, home, today):
    a, b, _, ids = home
    child = ids["수진"]
    client.post(f"/billing/allowances/{child}/credits", json={"amount": 10000}, headers=a)
    use = client.post(
        f"/billing/allowances/{child}/uses", json={"amount": 4000, "memo": "잘못 입력"}, headers=b
    ).json()
    entry = next(e for e in use["entries"] if e["kind"] == "use")
    voided = client.delete(f"/billing/allowances/{child}/entries/{entry['id']}", headers=b).json()
    assert voided["balance"] == 10000 and voided["total_use"] == 0  # 기록한 본인이 취소
    row = next(e for e in voided["entries"] if e["id"] == entry["id"])
    assert row["voided"] is True and row["balance_after"] is None  # 내역은 남는다
    assert (
        client.delete(f"/billing/allowances/{child}/entries/{entry['id']}", headers=a).json()[
            "code"
        ]
        == "already_voided"
    )
    assert client.delete(f"/billing/allowances/{child}/entries/nope", headers=a).status_code == 404


def test_void_permissions_and_a_credit_cannot_be_voided_below_zero(client, home, today):
    a, b, mom, ids = home
    child = ids["수진"]
    credit = client.post(
        f"/billing/allowances/{child}/credits", json={"amount": 5000}, headers=mom
    ).json()["entries"][0]
    client.post(f"/billing/allowances/{child}/uses", json={"amount": 3000}, headers=b)
    # 자녀는 부모가 기록한 입금을 취소할 수 없다
    kid = client.delete(f"/billing/allowances/{child}/entries/{credit['id']}", headers=b)
    assert kid.status_code == 403 and kid.json()["code"] == "not_allowed"
    # 이미 3000원을 써서 5000원 입금을 취소하면 잔액이 -3000원이 된다
    low = client.delete(f"/billing/allowances/{child}/entries/{credit['id']}", headers=mom)
    assert low.status_code == 400 and low.json()["code"] == "balance_negative"
    assert _ledger(client, a, child)["balance"] == 2000


def test_auto_credit_voided_is_not_posted_again(client, home, today):
    a, _, _, ids = home
    child = ids["수진"]
    today.set("2026-10-01")
    client.put(
        f"/billing/allowances/{child}/plan", json=_plan("monthly", 1, 7000, "auto"), headers=a
    )
    first = _ledger(client, a, child)
    assert first["balance"] == 7000
    client.delete(f"/billing/allowances/{child}/entries/{first['entries'][0]['id']}", headers=a)
    after = _ledger(client, a, child)
    assert after["balance"] == 0 and len(after["entries"]) == 1  # 같은 지급일을 다시 만들지 않는다
