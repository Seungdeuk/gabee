"""데일리 체크: 내 습관·오늘 기록 규칙, 날짜 경계, 순서, 가족 조회·요약, 응원, 온보딩 설정.

시계는 `check.now_utc` 를 바꿔 고정한다(한국 시간). 날짜는 2026-11-03(화요일)을 기준으로 한다.
"""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.shared.config import settings

from .. import check as check_service
from ..check import today_of
from ..models import CheckItem

KST = timezone(timedelta(hours=9))
TODAY = date(2026, 11, 3)  # 화요일(weekday() == 1)


@pytest.fixture
def clock(monkeypatch):
    """서버 시계를 한국 시간 2026-11-03 12:00 으로 고정하고, 바꿀 함수를 돌려준다."""
    monkeypatch.setattr(settings, "ai_day_utc_offset_hours", 9)

    def set_at(day: int, hour: int = 12, minute: int = 0, month: int = 11) -> None:
        now = datetime(2026, month, day, hour, minute, tzinfo=KST)
        monkeypatch.setattr(check_service, "now_utc", lambda: now)

    set_at(3)
    return set_at


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _item(client, headers, **over):
    body = {"name": "물 마시기", **over}
    return client.post("/schedule/check/items", json=body, headers=headers)


def _made(client, headers, **over) -> dict:
    r = _item(client, headers, **over)
    assert r.status_code == 201, r.text
    return r.json()


def _items(client, headers) -> list[dict]:
    r = client.get("/schedule/check/items", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _find(client, headers, item_id) -> dict:
    return next(i for i in _items(client, headers) if i["id"] == item_id)


def _entry(client, headers, item_id, **body):
    return client.put(f"/schedule/check/items/{item_id}/entry", json=body, headers=headers)


def _repeat_not_today() -> str:
    """오늘 요일만 꺼진 반복 요일 문자열."""
    days = ["1"] * 7
    days[TODAY.weekday()] = "0"
    return "".join(days)


# ---------------------------------------------------------------- 습관 CRUD
def test_item_crud_and_hard_delete(client, family, clock):
    a, _, _ = family
    made = _made(client, a)
    assert made["kind"] == 1 and made["goal"] is None and made["unit"] == ""
    assert made["repeat_days"] == "1111111" and made["shared"] is True and made["notify"] is False
    assert made["done"] is False and made["count"] is None and made["confirmed"] is False

    r = client.put(
        f"/schedule/check/items/{made['id']}",
        json={"name": "  물 두 잔  ", "notify": True},
        headers=a,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "물 두 잔" and r.json()["notify"] is True

    assert client.delete(f"/schedule/check/items/{made['id']}", headers=a).status_code == 204
    assert _items(client, a) == []
    # 진짜로 지워졌다: 행이 남지 않는다
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        assert db.get(CheckItem, made["id"]) is None
    assert client.delete(f"/schedule/check/items/{made['id']}", headers=a).status_code == 404


def test_create_validation_by_kind(client, family, clock):
    a, _, _ = family
    # 체크 습관에 목표·단위는 400
    assert _item(client, a, goal=3).status_code == 400
    assert _item(client, a, unit="잔").status_code == 400
    # 횟수 습관은 목표가 필요하다
    r = _item(client, a, kind=2, name="물")
    assert r.status_code == 400 and r.json()["code"] == "goal_required"
    # 목표·단위가 있는 횟수 습관은 만들 수 있다
    made = _made(client, a, kind=2, goal=8, unit="잔", name="물")
    assert made["goal"] == 8 and made["unit"] == "잔" and made["count"] == 0
    assert made["done"] is None
    # 요일을 하나도 고르지 않으면 400, 목표 범위 밖은 422
    assert _item(client, a, repeat_days="0000000").status_code == 400
    assert _item(client, a, kind=2, goal=0).status_code == 422
    assert _item(client, a, kind=2, goal=10000).status_code == 422


# ---------------------------------------------------------------- 체크 습관
def test_check_uncheck_and_recheck_rules(client, family, clock):
    a, _, _ = family
    item = _made(client, a)
    clock(3, 9, 0)
    r = _entry(client, a, item["id"], done=True)
    assert r.status_code == 200, r.text
    assert r.json()["done"] is True and r.json()["confirmed"] is True
    assert r.json()["confirmed_at"] is not None

    clock(3, 10, 0)
    assert _entry(client, a, item["id"], done=False).json()["done"] is False
    cleared = _find(client, a, item["id"])
    assert cleared["done"] is False and cleared["confirmed"] is False
    assert cleared["confirmed_at"] is None

    clock(3, 11, 0)
    again = _entry(client, a, item["id"], done=True).json()
    assert again["confirmed_at"].startswith("2026-11-03T02:00:00")  # 11:00 KST = 02:00 UTC
    # 체크 습관에 count 를 보내거나 done 을 빼면 400
    assert _entry(client, a, item["id"], count=3).status_code == 400
    assert _entry(client, a, item["id"]).status_code == 400


def test_entry_on_other_members_item_is_not_found(client, family, other_family, clock):
    a, _, _ = family
    item = _made(client, a)
    assert _entry(client, other_family, item["id"], done=True).status_code == 404


# ---------------------------------------------------------------- 횟수 습관
def test_count_over_goal_cap_and_zero_reset(client, family, clock):
    a, _, _ = family
    item = _made(client, a, kind=2, goal=3, name="물", unit="잔")
    r = _entry(client, a, item["id"], count=5)  # 목표를 넘겨도 된다
    assert r.status_code == 200 and r.json()["count"] == 5 and r.json()["confirmed"] is True
    assert _entry(client, a, item["id"], count=9999).json()["count"] == 9999
    assert _entry(client, a, item["id"], count=10000).status_code == 422
    assert _entry(client, a, item["id"], count=-1).status_code == 422

    under = _entry(client, a, item["id"], count=2).json()
    assert under["count"] == 2 and under["confirmed"] is False and under["confirmed_at"]

    zero = _entry(client, a, item["id"], count=0).json()
    assert zero["count"] == 0 and zero["confirmed"] is False and zero["confirmed_at"] is None

    # 횟수 습관에 done 을 보내거나 count 를 빼면 400
    assert _entry(client, a, item["id"], done=True).status_code == 400
    assert _entry(client, a, item["id"]).status_code == 400


def test_goal_change_recalculates_confirmed_and_keeps_count(client, family, clock):
    a, _, _ = family
    item = _made(client, a, kind=2, goal=3, name="물", unit="잔")
    _entry(client, a, item["id"], count=2)
    raised = client.put(f"/schedule/check/items/{item['id']}", json={"goal": 5}, headers=a).json()
    assert raised["count"] == 2 and raised["confirmed"] is False
    lowered = client.put(f"/schedule/check/items/{item['id']}", json={"goal": 2}, headers=a).json()
    assert lowered["count"] == 2 and lowered["confirmed"] is True
    # 체크 습관에 목표를 붙이면 400, 횟수 습관의 목표를 비우면 400
    assert (
        client.put(
            f"/schedule/check/items/{item['id']}", json={"goal": None}, headers=a
        ).status_code
        == 400
    )


def test_kind_change_resets_today_record(client, family, clock):
    a, _, _ = family
    item = _made(client, a)  # 체크 습관
    _entry(client, a, item["id"], done=True)
    to_count = client.put(
        f"/schedule/check/items/{item['id']}", json={"kind": 2, "goal": 4}, headers=a
    )
    assert to_count.status_code == 200, to_count.text
    body = to_count.json()
    assert body["kind"] == 2 and body["done"] is None and body["count"] == 0
    assert body["confirmed"] is False and body["confirmed_at"] is None

    _entry(client, a, item["id"], count=4)
    back = client.put(f"/schedule/check/items/{item['id']}", json={"kind": 1}, headers=a).json()
    assert back["kind"] == 1 and back["goal"] is None and back["unit"] == ""
    assert back["done"] is False and back["count"] is None and back["confirmed"] is False


# ---------------------------------------------------------------- 날짜 경계
def test_yesterday_record_shows_as_not_done_today(client, family, clock):
    a, _, _ = family
    item = _made(client, a)
    clock(2, 12, 0)  # 어제
    _entry(client, a, item["id"], done=True)
    clock(3, 0, 5)  # 오늘 자정 직후
    today = _find(client, a, item["id"])
    assert today["done"] is False and today["confirmed"] is False and today["confirmed_at"] is None


def test_count_is_zero_after_midnight_then_recorded_today(client, family, clock):
    a, _, _ = family
    item = _made(client, a, kind=2, goal=3, name="걷기", unit="보")
    clock(2, 23, 50)
    _entry(client, a, item["id"], count=3)
    clock(3, 0, 10)
    assert _find(client, a, item["id"])["count"] == 0
    # 자정이 지난 뒤 기록하면 오늘 기록이 된다
    clock(3, 0, 20)
    after = _entry(client, a, item["id"], count=1).json()
    assert after["count"] == 1 and after["confirmed"] is False
    assert _find(client, a, item["id"])["count"] == 1


def test_today_uses_korean_date_not_utc(client, family, clock):
    """한국 시간 2026-11-03 08:30 은 UTC 로는 11-02 23:30 이다. 오늘은 한국 날짜(11-03)로 본다."""
    assert today_of(datetime(2026, 11, 2, 23, 30, tzinfo=UTC)) == TODAY
    a, _, _ = family
    item = _made(client, a)
    clock(3, 8, 30)
    _entry(client, a, item["id"], done=True)
    assert _find(client, a, item["id"])["done"] is True


# ---------------------------------------------------------------- 순서
def test_reorder_must_cover_all_my_items(client, family, other_family, clock):
    a, _, _ = family
    ids = [_made(client, a, name=f"습관{i}")["id"] for i in range(3)]
    foreign = _made(client, other_family, name="남의 것")["id"]

    r = client.put("/schedule/check/items/order", json={"ids": list(reversed(ids))}, headers=a)
    assert r.status_code == 200, r.text
    assert [i["id"] for i in r.json()] == list(reversed(ids))
    assert [i["id"] for i in _items(client, a)] == list(reversed(ids))

    for bad in (ids[:2], ids + ids[:1], ids[:2] + [foreign], []):
        r = client.put("/schedule/check/items/order", json={"ids": bad}, headers=a)
        assert r.status_code == 400 and r.json()["code"] == "invalid_order", bad


# ---------------------------------------------------------------- 가족 조회·요약
def test_family_view_shows_only_shared_items_repeating_today(client, family, other_family, clock):
    a, b, _ = family
    shared_today = _made(client, b, name="안부 전화", shared=True)
    _made(client, b, name="비밀 습관", shared=False)
    _made(client, b, name="오늘 아닌 날", repeat_days=_repeat_not_today())
    _entry(client, b, shared_today["id"], done=True)
    b_id = _me(client, b)

    view = client.get(f"/schedule/check/members/{b_id}/today", headers=a).json()
    assert view["user_id"] == b_id and view["name"] == "수진"
    assert [i["name"] for i in view["items"]] == ["안부 전화"]
    assert view["items"][0]["done"] is True and view["items"][0]["confirmed"] is True
    assert "notify" not in view["items"][0] and "repeat_days" not in view["items"][0]
    # 꺼진 습관 이름은 응답 어디에도 없다
    assert "비밀 습관" not in str(view)

    # 같은 가족이 아니면 404(존재를 알리지 않는다)
    outsider = _me(client, other_family)
    assert client.get(f"/schedule/check/members/{outsider}/today", headers=a).status_code == 404
    assert (
        client.get(f"/schedule/check/members/{b_id}/today", headers=other_family).status_code == 404
    )


def test_members_summary_counts_repeat_days_and_done(client, family, clock):
    a, b, _ = family
    done_one = _made(client, b, name="물")
    _made(client, b, name="영양제")
    _made(client, b, name="오늘 쉬는 것", repeat_days=_repeat_not_today())
    _made(client, b, name="안 보이는 것", shared=False)
    _entry(client, b, done_one["id"], done=True)

    summary = client.get("/schedule/check/members/summary", headers=a).json()
    by_name = {row["name"]: row for row in summary}
    assert by_name["수진"]["total"] == 2 and by_name["수진"]["done"] == 1
    assert by_name["지민"]["total"] == 0 and by_name["지민"]["done"] == 0
    assert {row["user_id"] for row in summary} == {_me(client, a), _me(client, b)}


# ---------------------------------------------------------------- 응원
def _cheer(client, headers, to, **over):
    body = {"to_user_id": to, "kind": 1, "message": "오늘도 고마워요", **over}
    return client.post("/schedule/check/cheers", json=body, headers=headers)


def test_cheer_only_within_family_and_not_to_self(client, family, other_family, clock):
    a, b, _ = family
    a_id, b_id = _me(client, a), _me(client, b)
    assert _cheer(client, a, a_id).status_code == 400
    assert _cheer(client, a, _me(client, other_family)).status_code == 404
    r = _cheer(client, a, b_id, kind=3, message="잘하셨어요")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["from_name"] == "지민" and body["to_name"] == "수진"
    assert body["thanked_at"] is None and body["closed"] is False and body["chat_left"] is False


def test_cheer_validation(client, family, clock):
    a, b, _ = family
    b_id = _me(client, b)
    assert _cheer(client, a, b_id, kind=4).status_code == 422
    assert _cheer(client, a, b_id, message="   ").status_code == 422
    assert _cheer(client, a, b_id, message="가" * 101).status_code == 422
    assert _cheer(client, a, b_id, message="가" * 100).status_code == 201


def test_cheer_list_visibility_and_thanks_close_rules(client, family, other_family, clock):
    a, b, _ = family
    b_id = _me(client, b)
    cheer_id = _cheer(client, a, b_id).json()["id"]

    received = client.get("/schedule/check/cheers", headers=b).json()
    assert [c["id"] for c in received] == [cheer_id]
    assert client.get("/schedule/check/cheers?direction=sent", headers=b).json() == []
    sent = client.get("/schedule/check/cheers?direction=sent", headers=a).json()
    assert [c["id"] for c in sent] == [cheer_id]
    assert client.get("/schedule/check/cheers", headers=a).json() == []  # 받은 것만 보인다

    # 보낸 사람과 제3자는 고마워·닫기를 할 수 없다(404)
    for path in ("thanked", "closed"):
        for headers in (a, other_family):
            r = client.put(f"/schedule/check/cheers/{cheer_id}/{path}", headers=headers)
            assert r.status_code == 404, (path, r.text)

    # 받은 사람의 고마워는 보내면 끝(본문 없음). 처음 시각을 남기고, 다시 보내도 그대로다
    clock(3, 13, 0)
    first = client.put(f"/schedule/check/cheers/{cheer_id}/thanked", headers=b).json()
    assert first["thanked_at"] is not None
    clock(3, 14, 0)
    again = client.put(f"/schedule/check/cheers/{cheer_id}/thanked", headers=b).json()
    assert again["thanked_at"] == first["thanked_at"]  # 시각은 처음 것 그대로
    assert (
        client.get("/schedule/check/cheers", headers=b).json()[0]["thanked_at"]
        == first["thanked_at"]
    )

    # 닫기도 한 번만(되돌림 없음). 닫은 카드도 목록에는 남고 closed 로 구분된다
    closed = client.put(f"/schedule/check/cheers/{cheer_id}/closed", headers=b).json()
    assert closed["closed"] is True and closed["closed_at"] is not None
    closed_again = client.put(f"/schedule/check/cheers/{cheer_id}/closed", headers=b).json()
    assert closed_again["closed_at"] == closed["closed_at"]
    listed = client.get("/schedule/check/cheers", headers=b).json()
    assert len(listed) == 1 and listed[0]["closed"] is True


# ---------------------------------------------------------------- 설정
def test_settings_default_and_update(client, family, clock):
    a, _, _ = family
    assert client.get("/schedule/check/settings", headers=a).json() == {"onboarded": False}
    assert client.put("/schedule/check/settings", json={"onboarded": True}, headers=a).json() == {
        "onboarded": True
    }
    assert client.get("/schedule/check/settings", headers=a).json() == {"onboarded": True}
    assert client.put("/schedule/check/settings", json={"onboarded": False}, headers=a).json() == {
        "onboarded": False
    }


# ---------------------------------------------------------------- 기능 준비 점검
def test_check_tables_form_their_own_schema_feature():
    """체크 테이블은 일정 기능과 따로 점검된다: 준비 안 된 DB 면 체크 API 만 503 이 된다."""
    from app.shared.schema import feature_tables

    features = feature_tables()
    check = set(features["schedule_check"])
    assert check == {"events_check_items", "events_check_cheers", "events_check_settings"}
    assert not any(name.startswith("events_check_") for name in features["schedule"])


def test_missing_check_table_returns_503_only_for_check_api(client, family, clock, monkeypatch):
    """체크 테이블이 아직 없으면 /schedule/check 만 503(schema_not_ready), 일정의 나머지는 그대로 동작한다."""
    from sqlalchemy import text

    from app.shared.db import Base, engine
    from app.shared.schema import monitor

    a, _, _ = family
    monkeypatch.setattr(settings, "schema_recheck_ready_seconds", 0)
    monkeypatch.setattr(settings, "schema_recheck_not_ready_seconds", 0)
    monkeypatch.setattr(settings, "schema_force_min_interval_seconds", 0)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE events_check_settings"))
    monitor.reset()
    try:
        blocked = client.get("/schedule/check/settings", headers=a)
        assert blocked.status_code == 503 and blocked.json()["code"] == "schema_not_ready"
        assert client.get("/schedule/events", headers=a).status_code == 200
    finally:
        Base.metadata.tables["events_check_settings"].create(engine, checkfirst=True)
        monitor.reset()
    assert client.get("/schedule/check/settings", headers=a).status_code == 200
