"""데일리 체크, 누락 계산, 규칙 기반 추천, 식단 추천, 예시 위치."""

TODAY = "/care/daily"


def _items(client, headers, **params):
    return {i["name"]: i for i in client.get(TODAY, params=params, headers=headers).json()["items"]}


def _put(client, headers, item, **body):
    r = client.put(f"/care/items/{item['id']}/entry", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_seven_sample_items_and_add_delete(client, family):
    a, _, _ = family
    items = _items(client, a)
    assert set(items) == {"아침 식사", "영양제", "컨디션", "점심 식사", "물", "산책", "저녁 식사"}
    assert items["물"]["target"] == 1500 and items["물"]["unit"] == "ml"

    new = client.post(
        "/care/items",
        json={
            "name": "혈압",
            "mode": "number",
            "unit": "mmHg",
            "target": 130,
            "scheduled_time": "07:30",
        },
        headers=a,
    )
    assert new.status_code == 201
    assert "혈압" in _items(client, a)
    assert client.delete(f"/care/items/{new.json()['id']}", headers=a).status_code == 204
    assert "혈압" not in _items(client, a)
    assert len(_items(client, a)) == 7  # 샘플을 다시 만들지 않는다

    bad = client.post(
        "/care/items",
        json={"name": "x", "mode": "yesno", "target": 3, "scheduled_time": "07:30"},
        headers=a,
    )
    assert bad.json()["code"] == "invalid_item"


def test_missing_is_computed_by_server_after_60_minutes(client, family):
    a, _, _ = family
    # 영양제 예정 09:00 -> 10:00 까지는 누락 아님, 10:01 부터 누락
    assert _items(client, a, at="10:00")["영양제"]["missing"] is False
    assert _items(client, a, at="10:01")["영양제"]["missing"] is True
    assert _items(client, a, at="07:00")["영양제"]["missing"] is False

    supplement = _items(client, a)["영양제"]
    _put(client, a, supplement, done=True)
    assert _items(client, a, at="23:00")["영양제"]["missing"] is False
    _put(client, a, supplement, done=False)  # '아니오'는 완료가 아니다
    assert _items(client, a, at="23:00")["영양제"]["missing"] is True

    data = client.get(TODAY, params={"at": "23:00"}, headers=a).json()
    assert supplement["id"] in data["missing_ids"]
    assert client.get(TODAY, params={"at": "25:00"}, headers=a).json()["code"] == "invalid_time"


def test_number_item_completes_only_at_target_and_entry_modes(client, family):
    a, b, _ = family
    items = _items(client, a)
    water, mood = items["물"], items["컨디션"]
    _put(client, a, water, number=500)
    assert _items(client, a, at="23:00")["물"]["completed"] is False
    _put(client, b, water, number=1500)
    assert _items(client, a, at="23:00")["물"]["completed"] is True

    _put(client, a, mood, condition="bad")
    assert _items(client, a)["컨디션"]["entry"]["condition"] == "bad"
    wrong = client.put(f"/care/items/{mood['id']}/entry", json={"number": 3}, headers=a)
    assert wrong.json()["code"] == "value_required"
    assert client.put("/care/items/nope/entry", json={"done": True}, headers=a).status_code == 404


def test_recommendations_follow_rules(client, family):
    a, _, _ = family
    items = _items(client, a)
    rules = {
        r["rule"] for r in client.get("/care/recommendations", headers=a).json()["recommendations"]
    }
    assert rules == {"water", "walk", "condition", "supplement"}

    _put(client, a, items["물"], number=1000)
    _put(client, a, items["산책"], number=30)
    _put(client, a, items["컨디션"], condition="bad")
    _put(client, a, items["영양제"], done=True)
    recs = client.get("/care/recommendations", headers=a).json()["recommendations"]
    by_rule = {r["rule"]: r["text"] for r in recs}
    assert set(by_rule) == {"water", "condition"}
    assert "500ml" in by_rule["water"]

    _put(client, a, items["물"], number=1500)
    _put(client, a, items["컨디션"], condition="good")
    recs = client.get("/care/recommendations", headers=a).json()["recommendations"]
    assert [r["rule"] for r in recs] == ["none"]


def test_meals_only_unrecorded_and_cycle(client, family):
    a, _, _ = family
    items = _items(client, a)
    first = client.get("/care/meals", headers=a).json()["meals"]
    assert [m["meal"] for m in first] == ["breakfast", "lunch", "dinner"]

    _put(client, a, items["점심 식사"], done=True)
    meals = client.get("/care/meals", headers=a).json()["meals"]
    assert [m["meal"] for m in meals] == ["breakfast", "dinner"]

    seen, index = [], 0
    for _ in range(first[0]["total"] + 1):
        m = client.get("/care/meals/breakfast", params={"index": index}, headers=a).json()
        seen.append(m["menu"])
        index = m["next_index"]
    assert len(set(seen[:-1])) == first[0]["total"] and seen[-1] == seen[0]  # 한 바퀴 돌면 처음으로
    assert client.get("/care/meals/snack", headers=a).status_code == 404


def test_location_is_always_marked_as_example(client, family):
    a, _, _ = family
    loc = client.get("/care/location", headers=a).json()
    assert loc["is_example"] is True and "예시" in loc["notice"] and "예시" in loc["place"]
