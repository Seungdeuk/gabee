"""돌봄 에이전트의 취소·삭제 제안: 내가 한 기록만, 확인해야 실행되고 실행 때 다시 검사한다."""

from .test_care_agent_write import _llm, _meals, _post, _setup

DAY = "2026-10-20"
CHAT = {"message": "취소해줘"}


def _item(client, headers):
    daily = client.get("/care/daily", params={"date": DAY}, headers=headers).json()
    return next(i for i in daily["items"] if i["mode"] == "yesno")


def _record(client, headers, item_id):
    r = client.put(
        f"/care/items/{item_id}/entry", json={"done": True, "date": DAY}, headers=headers
    )
    assert r.status_code == 200, r.text


def _completed(client, headers, item_id):
    daily = client.get("/care/daily", params={"date": DAY}, headers=headers).json()
    return next(i for i in daily["items"] if i["id"] == item_id)["completed"]


def _meal(client, headers, menu="비빔밥", meal="lunch"):
    r = client.put(
        "/care/meal-log", json={"date": DAY, "meal": meal, "menu": menu}, headers=headers
    )
    assert r.status_code == 200, r.text


def test_own_item_record_is_cleared_only_after_confirm(client, family, monkeypatch):
    a, _, _ = family
    item = _item(client, a)
    _record(client, a, item["id"])
    _setup(monkeypatch, _llm("propose_clear_item", {"item_id": item["id"], "date": DAY}))
    r = _post(client, a, "/care/agent/chat", CHAT).json()
    assert r["tool_calls"] == ["propose_clear_item"]
    (p,) = r["proposals"]
    assert p["summary"] == f"안부 기록 취소: {DAY} {item['name']}"
    assert _completed(client, a, item["id"]) is True  # 제안만으로는 지워지지 않는다
    assert _post(client, a, "/care/agent/confirm", {"token": p["token"]}).status_code == 200
    assert _completed(client, a, item["id"]) is False
    assert _post(client, a, "/care/agent/confirm", {"token": p["token"]}).status_code == 409


def test_someone_elses_item_record_is_not_proposed(client, family, monkeypatch):
    a, b, _ = family
    item = _item(client, a)
    _record(client, b, item["id"])  # 수진이 기록
    _setup(monkeypatch, _llm("propose_clear_item", {"item_id": item["id"], "date": DAY}))
    assert (
        _post(client, a, "/care/agent/chat", CHAT).json()["proposals"] == []
    )  # 지민이 취소하려 함
    assert _completed(client, a, item["id"]) is True


def test_item_clear_rejects_unknown_item_missing_record_and_bad_date(client, family, monkeypatch):
    a, _, _ = family
    item = _item(client, a)  # 기록이 없는 항목
    for args in (
        {"item_id": "없는-항목", "date": DAY},
        {"item_id": item["id"], "date": DAY},
        {"item_id": item["id"], "date": "내일"},
    ):
        _setup(monkeypatch, _llm("propose_clear_item", args))
        assert _post(client, a, "/care/agent/chat", CHAT).json()["proposals"] == []


def test_item_clear_is_rechecked_at_confirm_time(client, family, monkeypatch):
    a, b, _ = family
    item = _item(client, a)
    _record(client, a, item["id"])
    _setup(monkeypatch, _llm("propose_clear_item", {"item_id": item["id"], "date": DAY}))
    (p,) = _post(client, a, "/care/agent/chat", CHAT).json()["proposals"]
    _record(client, b, item["id"])  # 제안 뒤에 수진이 같은 항목을 다시 기록(덮어씀)
    r = _post(client, a, "/care/agent/confirm", {"token": p["token"]})
    assert r.status_code == 400 and r.json()["code"] == "record_not_deletable"
    assert _completed(client, a, item["id"]) is True


def test_own_meal_log_is_deleted_only_after_confirm_and_checklist_stays(
    client, family, monkeypatch
):
    a, _, _ = family
    _meal(client, a)
    _setup(monkeypatch, _llm("propose_clear_meal", {"meal": "lunch", "date": DAY}))
    r = _post(client, a, "/care/agent/chat", CHAT).json()
    (p,) = r["proposals"]
    assert p["summary"] == f"식단 기록 삭제: {DAY} 점심 비빔밥"
    assert _meals(client, a) == [("lunch", "비빔밥")]
    assert _post(client, a, "/care/agent/confirm", {"token": p["token"]}).status_code == 200
    assert _meals(client, a) == []
    lunch = next(
        i
        for i in client.get("/care/daily", params={"date": DAY}, headers=a).json()["items"]
        if i.get("meal_type") == "lunch"
    )
    assert lunch["completed"] is True  # 먹은 사실(데일리 체크)은 그대로 남는다


def test_someone_elses_or_missing_meal_log_is_not_proposed(client, family, monkeypatch):
    a, b, _ = family
    _meal(client, b, "김치찌개", "dinner")  # 수진이 기록
    for args in (
        {"meal": "dinner", "date": DAY},  # 남의 기록
        {"meal": "breakfast", "date": DAY},  # 기록 없음
        {"meal": "snack", "date": DAY},  # 없는 끼니
    ):
        _setup(monkeypatch, _llm("propose_clear_meal", args))
        assert _post(client, a, "/care/agent/chat", CHAT).json()["proposals"] == []
    assert _meals(client, a) == [("dinner", "김치찌개")]


def test_meal_delete_token_is_not_usable_by_another_member(client, family, monkeypatch):
    a, b, _ = family
    _meal(client, a)
    _setup(monkeypatch, _llm("propose_clear_meal", {"meal": "lunch", "date": DAY}))
    (p,) = _post(client, a, "/care/agent/chat", CHAT).json()["proposals"]
    assert _post(client, b, "/care/agent/confirm", {"token": p["token"]}).status_code == 400
    assert _meals(client, a) == [("lunch", "비빔밥")]
