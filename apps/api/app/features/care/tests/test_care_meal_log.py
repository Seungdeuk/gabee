"""식단 기록: 끼니별 메뉴 기록(직접 입력/추천 메뉴), 날짜별 목록, 데일리 체크 연동, 가족 격리."""

from datetime import UTC, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def _today() -> str:
    return datetime.now(KST).date().isoformat()


def _day(offset: int) -> str:
    return (datetime.now(KST).date() - timedelta(days=offset)).isoformat()


def _put(client, headers, **body):
    return client.put("/care/meal-log", json=body, headers=headers)


def _list(client, headers, **params):
    r = client.get("/care/meal-log", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _slots(day):
    return {s["meal"]: s["log"] for s in day["slots"]}


def test_default_range_is_seven_days_with_three_empty_slots_each(client, family):
    a, _, _ = family
    got = _list(client, a)
    assert [d["date"] for d in got["days"]] == [_day(i) for i in range(7)]  # 최신 날짜부터
    assert got["end"] == _today() and got["start"] == _day(6)
    for d in got["days"]:
        assert [s["meal"] for s in d["slots"]] == ["breakfast", "lunch", "dinner"]
        assert [s["label"] for s in d["slots"]] == ["아침", "점심", "저녁"]
        assert all(s["log"] is None for s in d["slots"])


def test_record_a_meal_and_see_who_wrote_it(client, family):
    a, b, _ = family
    r = _put(client, a, meal="lunch", menu="  닭죽  ", note="소금 적게")
    assert r.status_code == 200
    log = r.json()
    assert (log["date"], log["meal"], log["menu"], log["note"], log["source"]) == (
        _today(),
        "lunch",
        "닭죽",
        "소금 적게",
        "typed",
    )
    assert log["recorded_by_name"] == "지민" and log["label"] == "점심"
    # 다른 가족 구성원도 같은 기록을 본다
    seen = _slots(_list(client, b)["days"][0])
    assert seen["lunch"]["menu"] == "닭죽" and seen["lunch"]["recorded_by_name"] == "지민"
    assert seen["breakfast"] is None and seen["dinner"] is None


def test_same_meal_same_day_is_overwritten_and_other_meals_are_independent(client, family):
    a, b, _ = family
    _put(client, a, meal="dinner", menu="된장찌개 정식")
    again = _put(client, b, meal="dinner", menu="북엇국", source="recommended")
    assert again.json()["menu"] == "북엇국" and again.json()["source"] == "recommended"
    _put(client, a, meal="breakfast", menu="야채죽")
    today = _slots(_list(client, a)["days"][0])
    assert (today["dinner"]["menu"], today["dinner"]["recorded_by_name"]) == ("북엇국", "수진")
    assert today["breakfast"]["menu"] == "야채죽"


def test_past_dates_are_allowed_and_future_dates_are_not(client, family):
    a, _, _ = family
    past = _put(client, a, meal="lunch", menu="잔치국수", date=_day(3))
    assert past.status_code == 200 and past.json()["date"] == _day(3)
    future = _put(
        client,
        a,
        meal="lunch",
        menu="미리",
        date=(datetime.now(KST).date() + timedelta(days=1)).isoformat(),
    )
    assert future.status_code == 400 and future.json()["code"] == "future_date"
    days = {d["date"]: _slots(d) for d in _list(client, a, days=7)["days"]}
    assert days[_day(3)]["lunch"]["menu"] == "잔치국수" and days[_today()]["lunch"] is None


def test_validation(client, family):
    a, _, _ = family
    assert _put(client, a, meal="lunch", menu="").status_code == 422
    assert _put(client, a, meal="lunch", menu="x" * 61).status_code == 422
    assert _put(client, a, meal="lunch", menu="a", note="x" * 121).status_code == 422
    assert _put(client, a, meal="snack", menu="과자").status_code == 422
    assert _put(client, a, meal="lunch", menu="a", source="photo").status_code == 422
    blank = _put(client, a, meal="lunch", menu="   ")
    assert blank.status_code == 400 and blank.json()["code"] == "invalid_menu"
    assert all(
        s["log"] is None for s in _list(client, a)["days"][0]["slots"]
    )  # 실패는 아무것도 만들지 않는다


def test_range_limits_and_end_date(client, family):
    a, _, _ = family
    for bad in (0, 32):
        r = client.get("/care/meal-log", params={"days": bad}, headers=a)
        assert r.status_code == 400 and r.json()["code"] == "invalid_days"
    assert len(_list(client, a, days=31)["days"]) == 31
    assert (
        client.get("/care/meal-log", params={"end": "2026-13-40"}, headers=a).json()["code"]
        == "invalid_date"
    )
    _put(client, a, meal="dinner", menu="북엇국", date="2026-10-01")
    got = _list(client, a, days=3, end="2026-10-02")
    assert [d["date"] for d in got["days"]] == ["2026-10-02", "2026-10-01", "2026-09-30"]
    assert _slots(got["days"][1])["dinner"]["menu"] == "북엇국"


def test_logging_a_meal_marks_the_daily_check_item_done_and_removes_it_from_recommendations(
    client, family
):
    a, _, _ = family
    daily = client.get("/care/daily", params={"at": "12:20"}, headers=a).json()
    lunch = next(i for i in daily["items"] if i["meal_type"] == "lunch")
    assert lunch["completed"] is False
    # 먼저 '아니오'로 기록해 둬도 식단을 기록하면 먹은 것으로 덮어쓴다
    client.put(f"/care/items/{lunch['id']}/entry", json={"done": False}, headers=a)
    _put(client, a, meal="lunch", menu="비빔밥", source="recommended")
    after = client.get("/care/daily", params={"at": "12:20"}, headers=a).json()
    item = next(i for i in after["items"] if i["id"] == lunch["id"])
    assert item["completed"] is True and item["entry"]["done"] is True and item["status"] == "done"
    meals = {m["meal"]: m["status"] for m in after["meals"]}
    assert meals["lunch"] == "done"
    suggest = client.get("/care/meals", headers=a).json()["meals"]
    assert "lunch" not in [m["meal"] for m in suggest]  # 이미 먹은 끼니는 추천하지 않는다


def test_skipped_meal_item_becomes_done_when_the_menu_is_logged(client, family):
    a, _, _ = family
    daily = client.get("/care/daily", params={"at": "12:20"}, headers=a).json()
    breakfast = next(i for i in daily["items"] if i["meal_type"] == "breakfast")
    client.put(f"/care/items/{breakfast['id']}/entry", json={"skipped": True}, headers=a)
    _put(client, a, meal="breakfast", menu="야채죽")
    item = next(
        i
        for i in client.get("/care/daily", params={"at": "12:20"}, headers=a).json()["items"]
        if i["id"] == breakfast["id"]
    )
    assert item["completed"] is True and item["skipped"] is False


def test_delete_removes_only_the_log_not_the_daily_check(client, family):
    a, _, _ = family
    _put(client, a, meal="dinner", menu="북엇국")
    assert (
        client.delete(
            "/care/meal-log", params={"date": _today(), "meal": "dinner"}, headers=a
        ).status_code
        == 204
    )
    assert _slots(_list(client, a)["days"][0])["dinner"] is None
    again = client.delete("/care/meal-log", params={"date": _today(), "meal": "dinner"}, headers=a)
    assert again.status_code == 404
    assert (
        client.delete(
            "/care/meal-log", params={"date": _today(), "meal": "brunch"}, headers=a
        ).status_code
        == 404
    )
    daily = client.get("/care/daily", params={"at": "23:00"}, headers=a).json()
    dinner = next(i for i in daily["items"] if i["meal_type"] == "dinner")
    assert dinner["completed"] is True  # 먹은 사실(데일리 체크)은 그대로


def test_other_families_do_not_see_or_overwrite_logs(client, family, other_family):
    a, _, _ = family
    _put(client, a, meal="lunch", menu="우리 집 메뉴")
    mine = _list(client, other_family)["days"][0]
    assert all(s["log"] is None for s in mine["slots"])
    theirs = _put(client, other_family, meal="lunch", menu="남의 집 메뉴")
    assert theirs.status_code == 200
    assert _slots(_list(client, a)["days"][0])["lunch"]["menu"] == "우리 집 메뉴"
    assert (
        client.delete(
            "/care/meal-log", params={"date": _today(), "meal": "lunch"}, headers=other_family
        ).status_code
        == 204
    )
    assert _slots(_list(client, a)["days"][0])["lunch"]["menu"] == "우리 집 메뉴"


def test_recorded_at_is_set_by_the_server(client, family):
    a, _, _ = family
    before = datetime.now(UTC) - timedelta(seconds=5)
    log = _put(client, a, meal="lunch", menu="비빔밥").json()
    assert (
        datetime.fromisoformat(log["recorded_at"].replace("Z", "+00:00")).replace(tzinfo=UTC)
        >= before
    )
