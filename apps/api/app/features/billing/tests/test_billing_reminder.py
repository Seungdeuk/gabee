"""정산 담당자와 월말 정산 알림: 정산하기를 안 한 지출을 월말(마지막 5일)·월초 지연(5일까지)에 담당자에게만 알린다."""

from tests.helpers import signup


def _add(client, headers, amount=1000, date="2026-10-12", title="장보기"):
    r = client.post(
        "/billing/expenses",
        json={"title": title, "amount": amount, "date": date},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _reminder(client, headers, on=None):
    r = client.get("/billing/settlement/reminder", params={"on": on} if on else {}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(client, headers):
    members = client.get("/family-group/groups/me", headers=headers).json()["members"]
    return {m["name"]: m["id"] for m in members}


def test_default_manager_is_the_group_owner(client, family):
    a, b, _ = family  # 지민이 그룹을 만들었다
    mine = client.get("/billing/settlement/manager", headers=a).json()
    other = client.get("/billing/settlement/manager", headers=b).json()
    assert (mine["manager_name"], mine["is_me"]) == ("지민", True)
    assert (other["manager_name"], other["is_me"]) == ("지민", False)


def test_set_manager_rules(client, family):
    a, b, group = family
    ids = _ids(client, a)
    c = signup(client, "민준")
    client.post("/family-group/groups/join", json={"code": group["invite_code"]}, headers=c)

    # 담당자가 아니고 그룹을 만든 사람도 아니면 바꿀 수 없다
    denied = client.put("/billing/settlement/manager", json={"user_id": ids["수진"]}, headers=b)
    assert denied.status_code == 403 and denied.json()["code"] == "not_manager"
    assert (
        client.put("/billing/settlement/manager", json={"user_id": "nobody"}, headers=a).json()[
            "code"
        ]
        == "invalid_manager"
    )

    ok = client.put("/billing/settlement/manager", json={"user_id": ids["수진"]}, headers=a)
    assert (
        ok.status_code == 200
        and ok.json()["manager_name"] == "수진"
        and ok.json()["is_me"] is False
    )
    assert client.get("/billing/settlement/manager", headers=b).json()["is_me"] is True
    # 새 담당자도, 그룹을 만든 사람도 다시 바꿀 수 있다. 그냥 구성원은 못 바꾼다
    assert (
        client.put(
            "/billing/settlement/manager", json={"user_id": ids["지민"]}, headers=b
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/billing/settlement/manager", json={"user_id": ids["수진"]}, headers=c
        ).status_code
        == 403
    )


def test_reminder_window_month_end_and_early_month_overdue(client, family):
    a, _, _ = family
    _add(client, a, date="2026-10-12")
    _add(client, a, 2000, date="2026-10-20")
    assert _reminder(client, a, "2026-10-26")["show"] is False  # 월말까지 5일: 아직 아님
    r = _reminder(client, a, "2026-10-27")  # 월말까지 4일
    assert (r["show"], r["kind"], r["month"], r["days_left"]) == (True, "month_end", "2026-10", 4)
    assert (r["unsettled_count"], r["unsettled_total"]) == (2, 3000)
    assert _reminder(client, a, "2026-10-31")["days_left"] == 0
    # 월초: 지난 달 정산이 밀려 있으면 알린다
    r = _reminder(client, a, "2026-11-03")
    assert (r["show"], r["kind"], r["month"], r["days_left"]) == (True, "overdue", "2026-10", None)
    assert _reminder(client, a, "2026-11-06")["show"] is False
    assert _reminder(client, a, "2026-11-06")["kind"] is None


def test_reminder_handles_short_and_leap_february(client, family):
    a, _, _ = family
    _add(client, a, date="2027-02-10")
    _add(client, a, date="2028-02-10")
    assert _reminder(client, a, "2027-02-23")["show"] is False  # 2월은 28일까지: 월말까지 5일
    assert _reminder(client, a, "2027-02-24")["show"] is True
    assert _reminder(client, a, "2028-02-24")["show"] is False  # 윤년은 29일까지
    assert _reminder(client, a, "2028-02-25")["show"] is True


def test_only_the_manager_gets_show_true(client, family):
    a, b, _ = family
    _add(client, a)
    for_manager = _reminder(client, a, "2026-10-29")
    for_other = _reminder(client, b, "2026-10-29")
    assert for_manager["show"] is True and for_manager["is_manager"] is True
    assert for_other["show"] is False and for_other["is_manager"] is False
    assert for_other["manager_name"] == "지민"
    # 담당자를 바꾸면 알림 대상도 바뀐다
    ids = _ids(client, a)
    client.put("/billing/settlement/manager", json={"user_id": ids["수진"]}, headers=a)
    assert _reminder(client, a, "2026-10-29")["show"] is False
    assert _reminder(client, b, "2026-10-29")["show"] is True


def test_settling_marks_expenses_and_clears_the_reminder(client, family):
    a, _, _ = family
    e1 = _add(client, a, 1000)
    e2 = _add(client, a, 2000)
    assert e1["settled"] is False
    body = {"month": "2026-10", "expense_ids": [e1["id"]], "tag": "all"}
    assert client.post("/billing/settlement/tag", json=body, headers=a).status_code == 200
    r = _reminder(client, a, "2026-10-29")
    assert (r["unsettled_count"], r["unsettled_total"]) == (1, 2000)
    listed = {
        x["id"]: x
        for x in client.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json()
    }
    assert listed[e1["id"]]["settled"] is True and listed[e2["id"]]["settled"] is False
    body["expense_ids"] = [e2["id"]]
    client.post("/billing/settlement/tag", json=body, headers=a)
    assert _reminder(client, a, "2026-10-29")["show"] is False


def test_deleted_expenses_do_not_count_and_bad_date_is_rejected(client, family):
    a, _, _ = family
    e = _add(client, a)
    client.delete(f"/billing/expenses/{e['id']}", headers=a)
    assert _reminder(client, a, "2026-10-29")["show"] is False
    bad = client.get("/billing/settlement/reminder", params={"on": "2026-13-40"}, headers=a)
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_date"
