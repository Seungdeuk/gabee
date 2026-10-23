"""구독 결제일 알림: 결제일 3일 전부터 결제한 사람에게만, 이미 지출을 만든 달은 표시."""

from tests.helpers import signup


def _family(client, family):
    a, b, group = family
    mom = signup(client, "엄마", role="parent")
    client.post("/family-group/groups/join", json={"code": group["invite_code"]}, headers=mom)
    members = client.get("/family-group/groups/me", headers=a).json()["members"]
    return {"지민": a, "수진": b, "엄마": mom}, {m["name"]: m["id"] for m in members}


def _add(client, headers, **body):
    r = client.post("/billing/subscriptions", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _upcoming(client, headers, on):
    r = client.get("/billing/subscriptions/upcoming", params={"on": on}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_only_subscriptions_within_three_days_are_listed_in_date_order(client, family):
    hdr, _ = _family(client, family)
    a = hdr["지민"]
    _add(client, a, kind="ott", name="오늘", monthly_fee=1000, billing_day=25)
    _add(client, a, kind="ott", name="사흘 뒤", monthly_fee=2000, billing_day=28)
    _add(client, a, kind="ott", name="나흘 뒤", monthly_fee=3000, billing_day=29)
    _add(client, a, kind="ott", name="이틀 뒤", billing_day=27)  # 금액을 아직 안 넣음
    got = _upcoming(client, a, "2026-10-25")
    assert got["show"] is True and got["within_days"] == 3
    assert [(i["name"], i["days_left"], i["due_date"]) for i in got["items"]] == [
        ("오늘", 0, "2026-10-25"),
        ("이틀 뒤", 2, "2026-10-27"),
        ("사흘 뒤", 3, "2026-10-28"),
    ]
    assert got["items"][1]["amount"] is None and got["items"][0]["amount"] == 1000


def test_nothing_to_show_when_no_payment_is_close(client, family):
    hdr, _ = _family(client, family)
    a = hdr["지민"]
    _add(client, a, kind="ott", name="넷플릭스", monthly_fee=17000, billing_day=25)
    got = _upcoming(client, a, "2026-10-10")
    assert got == {"show": False, "within_days": 3, "items": []}


def test_only_the_payer_is_notified(client, family):
    hdr, ids = _family(client, family)
    a, b, mom = hdr["지민"], hdr["수진"], hdr["엄마"]
    _add(client, a, kind="ott", name="지민이 결제", monthly_fee=1000, billing_day=26)
    _add(client, a, kind="ott", name="수진이 결제", billing_day=26, payer_id=ids["수진"])
    _add(client, a, kind="ott", name="결제자 없음", billing_day=26, payer_id=None)
    assert [i["name"] for i in _upcoming(client, a, "2026-10-25")["items"]] == ["지민이 결제"]
    assert [i["name"] for i in _upcoming(client, b, "2026-10-25")["items"]] == ["수진이 결제"]
    assert _upcoming(client, mom, "2026-10-25") == {"show": False, "within_days": 3, "items": []}


def test_items_without_a_billing_day_and_deleted_items_are_skipped(client, family):
    hdr, _ = _family(client, family)
    a = hdr["지민"]
    _add(client, a, kind="ott", name="결제일 없음", monthly_fee=1000)
    gone = _add(client, a, kind="ott", name="지운 것", billing_day=26)
    client.delete(f"/billing/subscriptions/{gone['id']}", headers=a)
    assert _upcoming(client, a, "2026-10-25")["items"] == []


def test_month_end_billing_day_rolls_over_short_months_and_to_next_month(client, family):
    hdr, _ = _family(client, family)
    a = hdr["지민"]
    _add(client, a, kind="telecom", name="통신비", monthly_fee=50000, billing_day=31)
    # 2월에는 31일이 없어 말일(28일)이 결제일
    feb = _upcoming(client, a, "2027-02-26")["items"]
    assert [(i["due_date"], i["days_left"]) for i in feb] == [("2027-02-28", 2)]
    # 이번 달 결제일이 지났으면 다음 달 결제일을 센다(연말 → 새해)
    _add(client, a, kind="ott", name="월초 결제", billing_day=2)
    dec = {
        i["name"]: (i["due_date"], i["days_left"])
        for i in _upcoming(client, a, "2026-12-30")["items"]
    }
    assert dec == {"통신비": ("2026-12-31", 1), "월초 결제": ("2027-01-02", 3)}
    # 결제일이 막 지난 날은 알리지 않는다
    assert _upcoming(client, a, "2026-10-26")["items"] == []


def test_expense_made_flag_follows_the_month_of_the_due_date(client, family):
    hdr, _ = _family(client, family)
    a = hdr["지민"]
    _add(client, a, kind="ott", name="넷플릭스", monthly_fee=17000, billing_day=30)
    assert _upcoming(client, a, "2026-10-28")["items"][0]["expense_made"] is False
    made = client.post("/billing/subscriptions/monthly", json={"month": "2026-10"}, headers=a)
    assert made.status_code == 201 and len(made.json()["created"]) == 1
    assert _upcoming(client, a, "2026-10-28")["items"][0]["expense_made"] is True
    # 결제일이 다음 달로 넘어가는 시점에는 다음 달 지출 기준이라 아직 만들지 않은 상태
    assert _upcoming(client, a, "2026-10-31")["items"] == []  # 31일엔 11/30 이 멀다
    assert _upcoming(client, a, "2026-11-28")["items"][0]["expense_made"] is False


def test_invalid_date_is_rejected_and_other_families_get_nothing(client, family, other_family):
    hdr, _ = _family(client, family)
    r = client.get(
        "/billing/subscriptions/upcoming", params={"on": "2026-13-40"}, headers=hdr["지민"]
    )
    assert r.status_code == 400 and r.json()["code"] == "invalid_date"
    _add(client, hdr["지민"], kind="ott", name="우리 집", billing_day=26)
    assert _upcoming(client, other_family, "2026-10-25")["items"] == []
