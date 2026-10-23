"""돌봄 화면 재구성: 끼니 한눈에 보기, 다가오는 일정, 지난 미기록 정리(소급 입력·건너뛰기·되돌리기)."""

from datetime import datetime, timedelta, timezone

from tests.helpers import signup

KST = timezone(timedelta(hours=9))


def _daily(client, headers, **params):
    r = client.get("/care/daily", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _by_name(data):
    return {i["name"]: i for i in data["items"]}


def _ids(data, key):
    names = {i["id"]: i["name"] for i in data["items"]}
    return [names[x] for x in data[key]]


def _put(client, headers, item, **body):
    return client.put(f"/care/items/{item['id']}/entry", json=body, headers=headers)


def test_statuses_at_a_given_time_and_the_feed_order(client, family):
    a, _, _ = family
    data = _daily(client, a, at="12:20")
    st = {n: i["status"] for n, i in _by_name(data).items()}
    assert st == {
        "아침 식사": "missing",
        "영양제": "missing",
        "컨디션": "missing",
        "점심 식사": "due",  # 12:00 예정, 60분 안
        "산책": "upcoming",
        "물": "upcoming",
        "저녁 식사": "upcoming",
    }
    assert _ids(data, "upcoming_ids") == [
        "점심 식사",
        "산책",
        "물",
        "저녁 식사",
    ]  # 지금 해야 할 것 → 다가오는 순서
    assert _ids(data, "cleanup_ids") == ["아침 식사", "영양제", "컨디션"]  # 지난 것, 예정 시각 순
    assert data["missing_ids"] == data["cleanup_ids"]
    items = _by_name(data)
    assert items["점심 식사"]["minutes_until"] == -20 and items["산책"][
        "minutes_until"
    ] == 17 * 60 - (12 * 60 + 20)


def test_status_boundaries_around_the_60_minute_grace(client, family):
    a, _, _ = family
    assert _by_name(_daily(client, a, at="07:59"))["아침 식사"]["status"] == "upcoming"
    assert _by_name(_daily(client, a, at="08:00"))["아침 식사"]["status"] == "due"
    assert (
        _by_name(_daily(client, a, at="09:00"))["아침 식사"]["status"] == "due"
    )  # 예정 + 60분까지는 아직
    assert _by_name(_daily(client, a, at="09:01"))["아침 식사"]["status"] == "missing"
    assert _daily(client, a, at="07:00")["cleanup_ids"] == []  # 아침 일찍엔 정리할 것이 없다


def test_meals_are_summarised_for_the_pinned_bar(client, family):
    a, _, _ = family
    data = _daily(client, a, at="12:20")
    assert [(m["meal"], m["label"], m["status"], m["answer"]) for m in data["meals"]] == [
        ("breakfast", "아침", "missing", None),
        ("lunch", "점심", "due", None),
        ("dinner", "저녁", "upcoming", None),
    ]
    items = _by_name(data)
    _put(client, a, items["아침 식사"], done=True)
    _put(client, a, items["점심 식사"], done=False)
    meals = {m["meal"]: m for m in _daily(client, a, at="12:20")["meals"]}
    assert (meals["breakfast"]["status"], meals["breakfast"]["answer"]) == ("done", "yes")
    assert (meals["lunch"]["status"], meals["lunch"]["answer"]) == (
        "due",
        "no",
    )  # '아니오'는 완료가 아니다
    assert meals["dinner"]["answer"] is None


def test_skip_removes_an_item_from_the_missing_list_without_completing_it(client, family):
    a, _, _ = family
    items = _by_name(_daily(client, a, at="12:20"))
    r = _put(client, a, items["영양제"], skipped=True)
    assert r.status_code == 200 and r.json()["skipped"] is True and r.json()["late"] is False
    data = _daily(client, a, at="12:20")
    sup = _by_name(data)["영양제"]
    assert (sup["status"], sup["skipped"], sup["missing"], sup["completed"]) == (
        "skipped",
        True,
        False,
        False,
    )
    assert "영양제" not in _ids(data, "cleanup_ids") and _ids(data, "skipped_ids") == ["영양제"]
    assert "영양제" not in _ids(data, "done_ids") and sup["id"] not in data["missing_ids"]
    # 값이 없어도 건너뛸 수 있고(모든 방식), 건너뛰지 않으면 값이 필요하다
    for name in ("물", "컨디션", "점심 식사"):
        assert _put(client, a, items[name], skipped=True).status_code == 200
    assert _put(client, a, items["산책"]).json()["code"] == "value_required"
    assert _put(client, a, items["산책"], skipped=False).json()["code"] == "value_required"


def test_recording_after_a_skip_replaces_the_skip_and_skip_clears_the_value(client, family):
    a, _, _ = family
    water = _by_name(_daily(client, a, at="12:20"))["물"]
    _put(client, a, water, number=700)
    _put(client, a, water, skipped=True)
    e = _by_name(_daily(client, a, at="12:20"))["물"]["entry"]
    assert (e["skipped"], e["number"]) == (True, None)  # 값은 지워진다
    _put(client, a, water, number=1500)
    w = _by_name(_daily(client, a, at="12:20"))["물"]
    assert (w["status"], w["completed"], w["entry"]["skipped"], w["entry"]["number"]) == (
        "done",
        True,
        False,
        1500,
    )


def test_undo_by_deleting_the_entry(client, family):
    a, _, _ = family
    item = _by_name(_daily(client, a, at="12:20"))["컨디션"]
    _put(client, a, item, skipped=True)
    assert _by_name(_daily(client, a, at="12:20"))["컨디션"]["status"] == "skipped"
    assert client.delete(f"/care/items/{item['id']}/entry", headers=a).status_code == 204
    assert (
        _by_name(_daily(client, a, at="12:20"))["컨디션"]["status"] == "missing"
    )  # 되돌리면 다시 정리 대상
    assert (
        client.delete(f"/care/items/{item['id']}/entry", headers=a).status_code == 404
    )  # 이미 없음
    assert client.delete("/care/items/nope/entry", headers=a).status_code == 404


def test_late_flag_marks_retroactive_entries(client, family):
    a, _, _ = family
    item = _by_name(_daily(client, a))["아침 식사"]
    yesterday = (datetime.now(KST) - timedelta(days=1)).date().isoformat()
    tomorrow = (datetime.now(KST) + timedelta(days=1)).date().isoformat()
    late = _put(client, a, item, done=True, date=yesterday).json()  # 어제 아침을 지금 기록 → 소급
    assert late["late"] is True
    early = _put(
        client, a, item, done=True, date=tomorrow
    ).json()  # 내일 아침을 미리 기록 → 소급 아님
    assert early["late"] is False


def test_past_days_are_all_missing_unless_done_or_skipped(client, family):
    a, _, _ = family
    yesterday = (datetime.now(KST) - timedelta(days=1)).date().isoformat()
    items = _by_name(_daily(client, a))
    _put(client, a, items["아침 식사"], done=True, date=yesterday)
    _put(client, a, items["영양제"], skipped=True, date=yesterday)
    data = _daily(client, a, date=yesterday, at="08:00")
    st = {n: i["status"] for n, i in _by_name(data).items()}
    assert st["아침 식사"] == "done" and st["영양제"] == "skipped"
    assert all(st[n] == "missing" for n in ("컨디션", "점심 식사", "산책", "물", "저녁 식사"))
    assert data["upcoming_ids"] == [] and all(i["minutes_until"] is None for i in data["items"])
    tomorrow = (datetime.now(KST) + timedelta(days=1)).date().isoformat()
    assert all(
        i["status"] == "upcoming" for i in _daily(client, a, date=tomorrow, at="23:00")["items"]
    )


def test_skipped_items_are_not_recommended_again(client, family):
    a, _, _ = family
    items = _by_name(_daily(client, a))

    def rules():
        recs = client.get("/care/recommendations", headers=a).json()["recommendations"]
        return {r["rule"] for r in recs}

    assert {"supplement", "water", "walk", "condition"} <= rules()
    for name in ("영양제", "물", "산책", "컨디션"):
        _put(client, a, items[name], skipped=True)
    assert rules() == {"none"}


def test_other_families_cannot_undo_my_entries(client, family):
    a, _, _ = family
    item = _by_name(_daily(client, a))["영양제"]
    _put(client, a, item, skipped=True)
    outsider = signup(client, "남의 집")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    assert client.delete(f"/care/items/{item['id']}/entry", headers=outsider).status_code == 404
    assert _by_name(_daily(client, a))["영양제"]["status"] == "skipped"
