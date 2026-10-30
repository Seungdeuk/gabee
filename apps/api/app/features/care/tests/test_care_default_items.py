"""새 가족이 처음 열 때 만들어지는 기본 항목: 식사 3개 + 영양제만 있고(매일 한 번 누르는 체크), 나머지는 사용자가 직접 추가한다."""

DEFAULT_NAMES = {"아침 식사", "영양제", "점심 식사", "저녁 식사"}


def _items(client, headers):
    r = client.get("/care/daily", headers=headers)
    assert r.status_code == 200, r.text
    return {i["name"]: i for i in r.json()["items"]}


def test_new_family_gets_only_the_four_check_items(client, family):
    a, _, _ = family
    items = _items(client, a)
    assert set(items) == DEFAULT_NAMES
    assert all(i["mode"] == "yesno" for i in items.values())  # 모두 한 번 누르는 체크
    assert [i["scheduled_time"] for i in items.values()] == ["08:00", "09:00", "12:00", "19:00"]
    assert len(_items(client, a)) == 4  # 다시 열어도 다시 만들지 않는다


def test_meal_items_still_drive_the_meal_recommendations(client, family):
    a, _, _ = family
    _items(client, a)
    r = client.get("/care/meals", headers=a)
    assert r.status_code == 200, r.text
    assert {m["meal"] for m in r.json()["meals"]} == {"breakfast", "lunch", "dinner"}


def test_recommendations_work_without_the_removed_items(client, family):
    a, _, _ = family
    _items(client, a)
    r = client.get("/care/recommendations", headers=a)
    assert r.status_code == 200, r.text
    rules = {x["rule"] for x in r.json()["recommendations"]}
    assert rules <= {"supplement"}  # 물·산책·컨디션 항목이 없으니 그 추천은 나오지 않는다


def test_user_can_add_a_check_item_and_record_it_with_one_tap(client, family):
    a, _, _ = family
    _items(client, a)
    added = client.post(
        "/care/items",
        json={"name": "혈압약 먹기", "mode": "yesno", "scheduled_time": "07:30"},
        headers=a,
    )
    assert added.status_code in (200, 201), added.text
    item = _items(client, a)["혈압약 먹기"]
    assert item["mode"] == "yesno"
    done = client.put(f"/care/items/{item['id']}/entry", json={"done": True}, headers=a)
    assert done.status_code == 200, done.text
    assert _items(client, a)["혈압약 먹기"]["entry"]["done"] is True
