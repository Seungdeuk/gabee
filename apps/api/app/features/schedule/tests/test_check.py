"""데일리 체크: 습관·날짜별 기록 규칙, 날짜 경계, 메모, 소프트 삭제, 순서, 가족 조회·요약, 응원, 온보딩 설정.

시계는 `check.now_utc` 를 바꿔 고정한다(한국 시간). 날짜는 2026-11-03(화요일)을 기준으로 한다.
기록은 날짜별 줄(`events_check_logs`)에 쌓이므로, 지난 날을 쓰려면 그 날 이전에 습관을 만들어 둔다.
"""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.shared.config import settings

from .. import check as check_service
from ..check import today_of
from ..models import CheckItem, CheckLog

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


def _items(client, headers, day: date | None = None) -> list[dict]:
    params = {"date": day.isoformat()} if day else None
    r = client.get("/schedule/check/items", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _find(client, headers, item_id, day: date | None = None) -> dict:
    return next(i for i in _items(client, headers, day) if i["id"] == item_id)


def _entry(client, headers, item_id, day: date | None = None, **body):
    params = {"date": day.isoformat()} if day else None
    return client.put(
        f"/schedule/check/items/{item_id}/entry", json=body, params=params, headers=headers
    )


def _note(client, headers, item_id, note, day: date | None = None, **extra):
    params = {"date": day.isoformat()} if day else None
    return client.put(
        f"/schedule/check/items/{item_id}/note",
        json={"note": note, **extra},
        params=params,
        headers=headers,
    )


def _repeat_not_today() -> str:
    """오늘 요일만 꺼진 반복 요일 문자열."""
    days = ["1"] * 7
    days[TODAY.weekday()] = "0"
    return "".join(days)


def _db_logs(item_id: str) -> list[CheckLog]:
    """DB 에 있는 그 습관의 줄 전부(API 를 거치지 않고 직접 읽는다)."""
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        rows = db.query(CheckLog).filter(CheckLog.item_id == item_id).all()
        for row in rows:
            db.expunge(row)
        return rows


def _db_item(item_id: str) -> CheckItem | None:
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        item = db.get(CheckItem, item_id)
        if item is not None:
            db.expunge(item)
        return item


# ---------------------------------------------------------------- 습관 CRUD
def test_item_crud_and_defaults(client, family, clock):
    a, _, _ = family
    made = _made(client, a)
    assert made["kind"] == 1 and made["goal"] is None and made["unit"] == ""
    assert made["repeat_days"] == "1111111" and made["shared"] is True and made["notify"] is False
    assert made["done"] is False and made["count"] is None and made["confirmed"] is False
    assert made["note"] is None and made["note_shared"] is False

    r = client.put(
        f"/schedule/check/items/{made['id']}",
        json={"name": "  물 두 잔  ", "notify": True},
        headers=a,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "물 두 잔" and r.json()["notify"] is True


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


def test_creating_item_makes_no_log_row(client, family, clock):
    """줄은 첫 기록 때만 만든다. 습관을 만들고 목록을 읽어도 줄은 생기지 않는다."""
    a, _, _ = family
    item = _made(client, a)
    _items(client, a)
    assert _db_logs(item["id"]) == []


# ---------------------------------------------------------------- 소프트 삭제
def test_soft_delete_hides_item_and_keeps_logs(client, family, clock):
    a, b, _ = family
    item = _made(client, a)
    _entry(client, a, item["id"], done=True)
    shared = _made(client, b, name="안부 전화")
    _entry(client, b, shared["id"], done=True)

    assert client.delete(f"/schedule/check/items/{item['id']}", headers=a).status_code == 204
    assert _items(client, a) == []

    # 행은 남고 deleted_at 만 채워진다. 지난 기록 줄도 그대로다
    deleted = _db_item(item["id"])
    assert deleted is not None and deleted.deleted_at is not None
    assert [log.done for log in _db_logs(item["id"])] == [True]

    # 지운 습관에는 기록·메모·다시 지우기가 모두 404
    assert _entry(client, a, item["id"], done=False).status_code == 404
    assert _note(client, a, item["id"], "메모").status_code == 404
    assert client.delete(f"/schedule/check/items/{item['id']}", headers=a).status_code == 404

    # 지운 습관은 가족 요약에도 나오지 않는다
    assert client.delete(f"/schedule/check/items/{shared['id']}", headers=b).status_code == 204
    summary = {
        row["name"]: row for row in client.get("/schedule/check/members/summary", headers=a).json()
    }
    assert summary["수진"]["total"] == 0


def test_deleted_item_is_excluded_from_reorder(client, family, clock):
    a, _, _ = family
    keep = _made(client, a, name="남김")
    gone = _made(client, a, name="지움")
    client.delete(f"/schedule/check/items/{gone['id']}", headers=a)
    # 지운 습관 id 를 순서에 넣으면 남의 습관처럼 400
    r = client.put("/schedule/check/items/order", json={"ids": [keep["id"], gone["id"]]}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "invalid_order"
    r = client.put("/schedule/check/items/order", json={"ids": [keep["id"]]}, headers=a)
    assert r.status_code == 200


# ---------------------------------------------------------------- 줄 생성·created_at
def test_log_row_created_once_and_created_at_never_changes(client, family, clock):
    a, _, _ = family
    item = _made(client, a)
    clock(3, 13, 0)
    _entry(client, a, item["id"], done=True)
    first = _db_logs(item["id"])
    assert len(first) == 1
    created = first[0].created_at

    clock(3, 14, 0)
    _entry(client, a, item["id"], done=False)
    clock(3, 15, 0)
    _note(client, a, item["id"], "오후 메모")
    clock(3, 16, 0)
    _entry(client, a, item["id"], done=True)

    rows = _db_logs(item["id"])
    assert len(rows) == 1  # 같은 날은 한 줄
    assert rows[0].created_at == created  # 줄이 처음 생긴 시각은 바뀌지 않는다
    assert rows[0].note == "오후 메모"


def test_uncheck_or_clear_without_a_row_creates_nothing(client, family, clock):
    a, _, _ = family
    item = _made(client, a)
    assert _entry(client, a, item["id"], done=False).status_code == 200
    assert _note(client, a, item["id"], "   ").status_code == 200  # 공백만 있으면 지우기
    assert _note(client, a, item["id"], None).status_code == 200
    assert _db_logs(item["id"]) == []


# ---------------------------------------------------------------- 체크 습관
def test_check_uncheck_and_recheck_rules(client, family, clock):
    a, _, _ = family
    item = _made(client, a)
    clock(3, 9, 0)
    r = _entry(client, a, item["id"], done=True)
    assert r.status_code == 200, r.text
    assert r.json()["done"] is True and r.json()["confirmed"] is True
    assert r.json()["confirmed_at"].startswith("2026-11-03T00:00:00")  # 09:00 KST = 00:00 UTC

    # 이미 체크된 상태에서 다시 체크해도 처음 체크한 시각은 그대로다
    clock(3, 9, 30)
    again = _entry(client, a, item["id"], done=True).json()
    assert again["confirmed_at"].startswith("2026-11-03T00:00:00")

    clock(3, 10, 0)
    assert _entry(client, a, item["id"], done=False).json()["done"] is False
    cleared = _find(client, a, item["id"])
    assert cleared["done"] is False and cleared["confirmed"] is False
    assert cleared["confirmed_at"] is None

    # 취소 뒤 다시 체크하면 완료 시각은 새로 찍힌다
    clock(3, 11, 0)
    recheck = _entry(client, a, item["id"], done=True).json()
    assert recheck["confirmed_at"].startswith("2026-11-03T02:00:00")  # 11:00 KST = 02:00 UTC
    # 체크 습관에 count 를 보내거나 done 을 빼면 400
    assert _entry(client, a, item["id"], count=3).status_code == 400
    assert _entry(client, a, item["id"]).status_code == 400


def test_entry_on_other_members_item_is_not_found(client, family, other_family, clock):
    a, _, _ = family
    item = _made(client, a)
    assert _entry(client, other_family, item["id"], done=True).status_code == 404


# ---------------------------------------------------------------- 횟수 습관
def test_count_cap_zero_and_zero_without_row(client, family, clock):
    a, _, _ = family
    item = _made(client, a, kind=2, goal=3, name="물", unit="잔")
    r = _entry(client, a, item["id"], count=5)  # 목표를 넘겨도 된다
    assert r.status_code == 200 and r.json()["count"] == 5 and r.json()["confirmed"] is True
    assert _entry(client, a, item["id"], count=9999).json()["count"] == 9999
    assert _entry(client, a, item["id"], count=10000).status_code == 422
    assert _entry(client, a, item["id"], count=-1).status_code == 422

    zero = _entry(client, a, item["id"], count=0).json()
    assert zero["count"] == 0 and zero["confirmed"] is False and zero["confirmed_at"] is None

    # 횟수 습관에 done 을 보내거나 count 를 빼면 400
    assert _entry(client, a, item["id"], done=True).status_code == 400
    assert _entry(client, a, item["id"]).status_code == 400

    # 줄이 없는 날에 0 을 적으면 줄을 만들지 않는다
    other = _made(client, a, kind=2, goal=2, name="걷기", unit="보")
    _entry(client, a, other["id"], count=0)
    assert _db_logs(other["id"]) == []


def test_count_confirmed_at_only_on_first_reach(client, family, clock):
    a, _, _ = family
    item = _made(client, a, kind=2, goal=3, name="물", unit="잔")
    clock(3, 9, 0)
    first = _entry(client, a, item["id"], count=3).json()
    assert first["confirmed"] is True and first["confirmed_at"].startswith("2026-11-03T00:00:00")

    clock(3, 10, 0)  # 완료 상태에서 더 올려도 완료 시각은 바뀌지 않는다
    over = _entry(client, a, item["id"], count=5).json()
    assert over["confirmed"] is True and over["confirmed_at"].startswith("2026-11-03T00:00:00")

    clock(3, 11, 0)  # 목표 아래로 내리면 완료를 취소하고 시각을 지운다
    under = _entry(client, a, item["id"], count=2).json()
    assert under["count"] == 2 and under["confirmed"] is False and under["confirmed_at"] is None

    clock(3, 12, 0)  # 다시 목표에 닿으면 그때 새로 찍는다
    reached = _entry(client, a, item["id"], count=4).json()
    assert reached["confirmed"] is True and reached["confirmed_at"].startswith(
        "2026-11-03T03:00:00"
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


def test_goal_change_recalculates_only_today_row(client, family, clock):
    a, _, _ = family
    clock(1, 9, 0)
    item = _made(client, a, kind=2, goal=3, name="물", unit="잔")  # 11-01 에 만든 습관
    clock(3)
    clock(2, 12, 0)
    _entry(client, a, item["id"], count=3)  # 어제: 목표 3 에 닿아 완료
    clock(3, 12, 0)
    _entry(client, a, item["id"], count=2)  # 오늘: 아직 미완료

    raised = client.put(f"/schedule/check/items/{item['id']}", json={"goal": 5}, headers=a).json()
    assert raised["count"] == 2 and raised["confirmed"] is False
    lowered = client.put(f"/schedule/check/items/{item['id']}", json={"goal": 2}, headers=a).json()
    assert lowered["count"] == 2 and lowered["confirmed"] is True
    assert lowered["confirmed_at"] is not None

    # 어제 줄은 목표를 바꿔도 그대로다(목표 스냅샷 3, 완료)
    yesterday = _find(client, a, item["id"], date(2026, 11, 2))
    assert yesterday["count"] == 3 and yesterday["confirmed"] is True
    client.put(f"/schedule/check/items/{item['id']}", json={"goal": 10}, headers=a)
    assert _find(client, a, item["id"], date(2026, 11, 2))["confirmed"] is True
    snapshot = [log.goal for log in _db_logs(item["id"]) if log.log_date == date(2026, 11, 2)]
    assert snapshot == [3]

    # 체크 습관에 목표를 붙이거나 횟수 습관의 목표를 비우면 400
    assert (
        client.put(
            f"/schedule/check/items/{item['id']}", json={"goal": None}, headers=a
        ).status_code
        == 400
    )


def test_kind_change_keeps_note_and_past_rows(client, family, clock):
    a, _, _ = family
    clock(1, 9, 0)
    item = _made(client, a, name="산책")  # 11-01 에 만든 습관
    clock(3)
    clock(2, 12, 0)
    _entry(client, a, item["id"], done=True)  # 어제 체크
    clock(3, 9, 0)
    _entry(client, a, item["id"], done=True)
    _note(client, a, item["id"], "오늘 메모")

    changed = client.put(
        f"/schedule/check/items/{item['id']}", json={"kind": 2, "goal": 4}, headers=a
    ).json()
    assert changed["done"] is None and changed["count"] == 0
    assert changed["confirmed"] is False and changed["confirmed_at"] is None
    assert changed["note"] == "오늘 메모"  # 메모는 남는다

    # 어제 줄은 건드리지 않는다(done 이 그대로 남아 있다)
    yesterday = [log for log in _db_logs(item["id"]) if log.log_date == date(2026, 11, 2)]
    assert len(yesterday) == 1 and yesterday[0].done is True


# ---------------------------------------------------------------- 날짜 경계
def test_yesterday_record_shows_only_on_its_date(client, family, clock):
    a, _, _ = family
    clock(1, 9, 0)
    item = _made(client, a)  # 11-01 에 만든 습관
    clock(2, 12, 0)
    _entry(client, a, item["id"], done=True)
    clock(3, 0, 5)  # 오늘 자정 직후
    today = _find(client, a, item["id"])
    assert today["done"] is False and today["confirmed"] is False and today["confirmed_at"] is None
    yesterday = _find(client, a, item["id"], date(2026, 11, 2))
    assert yesterday["done"] is True and yesterday["confirmed"] is True


def test_count_is_zero_after_midnight_then_recorded_today(client, family, clock):
    a, _, _ = family
    clock(1, 9, 0)
    item = _made(client, a, kind=2, goal=3, name="걷기", unit="보")
    clock(2, 23, 50)
    _entry(client, a, item["id"], count=3)
    clock(3, 0, 10)
    assert _find(client, a, item["id"])["count"] == 0
    clock(3, 0, 20)  # 자정이 지난 뒤 기록하면 오늘 기록이 된다
    after = _entry(client, a, item["id"], count=1).json()
    assert after["count"] == 1 and after["confirmed"] is False
    assert _find(client, a, item["id"])["count"] == 1


def test_date_range_is_today_to_seven_days_back(client, family, clock):
    a, _, _ = family
    clock(20, 9, 0, month=10)
    item = _made(client, a, kind=2, goal=2, name="물", unit="잔")  # 10-20 에 만든 습관
    clock(3)

    edge = date(2026, 10, 27)  # 오늘에서 7일 전: 허용
    assert _find(client, a, item["id"], edge)["count"] == 0
    assert _entry(client, a, item["id"], edge, count=2).status_code == 200
    assert _note(client, a, item["id"], "오래된 메모", edge).status_code == 200

    too_old = date(2026, 10, 26)  # 8일 전: 400
    for resp in (
        client.get("/schedule/check/items", params={"date": too_old.isoformat()}, headers=a),
        _entry(client, a, item["id"], too_old, count=1),
        _note(client, a, item["id"], "메모", too_old),
    ):
        assert resp.status_code == 400 and resp.json()["code"] == "date_out_of_range"

    tomorrow = date(2026, 11, 4)  # 미래: 400
    assert _entry(client, a, item["id"], tomorrow, count=1).status_code == 400
    assert _note(client, a, item["id"], "미래", tomorrow).status_code == 400


def test_entry_before_item_creation_is_400(client, family, clock):
    a, _, _ = family
    item = _made(client, a)  # 11-03 에 만든 습관
    yesterday = date(2026, 11, 2)
    for resp in (
        _entry(client, a, item["id"], yesterday, done=True),
        _note(client, a, item["id"], "어제 메모", yesterday),
    ):
        assert resp.status_code == 400 and resp.json()["code"] == "before_item_created"
    # 만든 날(오늘)은 된다
    assert _entry(client, a, item["id"], done=True).status_code == 200


def test_non_repeat_day_is_still_recordable(client, family, clock):
    """반복 요일이 아닌 날도 기록할 수 있다. 반복 요일은 목록에 나올지에만 쓴다."""
    a, _, _ = family
    item = _made(client, a, repeat_days=_repeat_not_today())  # 오늘(화) 꺼짐
    assert _entry(client, a, item["id"], done=True).status_code == 200
    assert _note(client, a, item["id"], "메모").status_code == 200
    assert _find(client, a, item["id"])["done"] is True


def test_today_uses_korean_date_not_utc(client, family, clock):
    """한국 시간 2026-11-03 08:30 은 UTC 로는 11-02 23:30 이다. 오늘은 한국 날짜(11-03)로 본다."""
    assert today_of(datetime(2026, 11, 2, 23, 30, tzinfo=UTC)) == TODAY
    a, _, _ = family
    item = _made(client, a)
    clock(3, 8, 30)
    _entry(client, a, item["id"], done=True)
    assert _find(client, a, item["id"])["done"] is True


# ---------------------------------------------------------------- 메모
def test_note_save_clear_and_limits(client, family, clock):
    a, _, _ = family
    item = _made(client, a)
    saved = _note(client, a, item["id"], "  물을 많이 마심  ").json()
    assert saved["note"] == "물을 많이 마심" and saved["note_shared"] is False
    assert saved["done"] is False and saved["confirmed"] is False  # 메모만으로는 완료가 아니다
    assert _find(client, a, item["id"])["note"] == "물을 많이 마심"

    # 100자는 되고 101자는 422
    assert _note(client, a, item["id"], "가" * 100).status_code == 200
    assert _note(client, a, item["id"], "가" * 101).status_code == 422
    assert _note(client, a, item["id"], "메모" * 60).status_code == 422
    # 메모 키가 없으면 422
    assert (
        client.put(f"/schedule/check/items/{item['id']}/note", json={}, headers=a).status_code
        == 422
    )

    # 빈 문자열·null 이면 메모를 지우고 줄은 남긴다
    _note(client, a, item["id"], "다시 쓸 메모", note_shared=True)
    cleared = _note(client, a, item["id"], "").json()
    assert cleared["note"] is None and cleared["note_shared"] is False
    assert len(_db_logs(item["id"])) == 1
    _note(client, a, item["id"], "또 쓰기")
    assert _note(client, a, item["id"], None).json()["note"] is None


def test_note_is_per_day(client, family, clock):
    a, _, _ = family
    clock(1, 9, 0)
    item = _made(client, a)
    clock(3, 9, 0)
    _note(client, a, item["id"], "오늘 것")
    _note(client, a, item["id"], "어제 것", date(2026, 11, 2))
    assert _find(client, a, item["id"])["note"] == "오늘 것"
    assert _find(client, a, item["id"], date(2026, 11, 2))["note"] == "어제 것"


def test_note_shared_visibility_to_family(client, family, other_family, clock):
    a, b, _ = family
    clock(1, 9, 0)
    shared = _made(client, b, name="안부 전화", shared=True)  # 11-01 에 만든 습관
    hidden_item = _made(client, b, name="비공개 습관", shared=False)
    clock(3)
    b_id = _me(client, b)

    # 메모만 쓰고 공유를 끈 상태: 가족에게는 메모가 없다
    _note(client, b, shared["id"], "엄마 생신 챙기기")
    view = client.get(f"/schedule/check/members/{b_id}/today", headers=a).json()
    assert view["items"][0]["note"] is None
    assert "엄마 생신" not in str(view)

    # 공유를 켜면 가족에게 보인다
    _note(client, b, shared["id"], "엄마 생신 챙기기", note_shared=True)
    view = client.get(f"/schedule/check/members/{b_id}/today", headers=a).json()
    assert view["items"][0]["note"] == "엄마 생신 챙기기"
    assert "note_shared" not in view["items"][0]

    # 습관이 가족에게 보이지 않으면 메모가 공유되어 있어도 습관 자체가 나오지 않는다
    _note(client, b, hidden_item["id"], "비밀 메모", note_shared=True)
    view = client.get(f"/schedule/check/members/{b_id}/today", headers=a).json()
    assert [i["name"] for i in view["items"]] == ["안부 전화"]
    assert "비밀 메모" not in str(view) and "비공개 습관" not in str(view)

    # 어제 메모를 공유로 켜 둬도 가족의 오늘 조회에는 안 나온다(오늘 줄만 읽는다)
    _note(client, b, shared["id"], "어제 메모", date(2026, 11, 2), note_shared=True)
    view = client.get(f"/schedule/check/members/{b_id}/today", headers=a).json()
    assert "어제 메모" not in str(view)

    # 지난 날 메모는 나의 조회에서는 보인다
    assert _find(client, b, shared["id"], date(2026, 11, 2))["note"] == "어제 메모"

    # 같은 가족이 아니면 404 그대로
    assert (
        client.get(f"/schedule/check/members/{b_id}/today", headers=other_family).status_code == 404
    )


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
    assert view["items"][0]["note"] is None
    # 꺼진 습관 이름은 응답 어디에도 없다
    assert "비밀 습관" not in str(view)

    # 같은 가족이 아니면 404(존재를 알리지 않는다)
    outsider = _me(client, other_family)
    assert client.get(f"/schedule/check/members/{outsider}/today", headers=a).status_code == 404
    assert (
        client.get(f"/schedule/check/members/{b_id}/today", headers=other_family).status_code == 404
    )


def test_members_summary_counts_repeat_days_and_done_today_only(client, family, clock):
    a, b, _ = family
    clock(2, 12, 0)
    yesterday_only = _made(client, b, name="어제 한 것")  # 11-02 에 만든 습관(어제 기록)
    clock(3, 12, 0)
    done_one = _made(client, b, name="물")
    _made(client, b, name="영양제")
    _made(client, b, name="오늘 쉬는 것", repeat_days=_repeat_not_today())
    _made(client, b, name="안 보이는 것", shared=False)
    _entry(client, b, done_one["id"], done=True)
    _entry(client, b, yesterday_only["id"], date(2026, 11, 2), done=True)

    summary = client.get("/schedule/check/members/summary", headers=a).json()
    by_name = {row["name"]: row for row in summary}
    assert by_name["수진"]["total"] == 3 and by_name["수진"]["done"] == 1
    assert by_name["지민"]["total"] == 0 and by_name["지민"]["done"] == 0
    assert {row["user_id"] for row in summary} == {_me(client, a), _me(client, b)}


def test_family_summary_excludes_removed_members_or_fails_safely(client, family, clock):
    """그룹 밖 사람은 요약에 없다(구성원 기준)."""
    a, b, _ = family
    summary_ids = {
        row["user_id"] for row in client.get("/schedule/check/members/summary", headers=b).json()
    }
    assert summary_ids == {_me(client, a), _me(client, b)}


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
    assert check == {
        "events_check_items",
        "events_check_logs",
        "events_check_cheers",
        "events_check_settings",
    }
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


# ---------------------------------------------------------------- 반복 요일 변경
ALL_ON = "1111111"
TUE_OFF = "1011111"  # 화요일(인덱스 1)만 꺼짐
SUN_OFF = "1111110"


def _applies(client, headers, item_id, day: date | None = None) -> bool:
    return _find(client, headers, item_id, day)["applies"]


def test_repeat_change_applies_new_pattern_from_change_day(client, family, clock):
    """요일을 바꾼 날(KST) 이후는 새 요일이 적용된다. 변경 전 날짜는 기록 줄이 있는 습관만 켜진다."""
    a, _, _ = family
    clock(1, 9, 0)
    item = _made(client, a, repeat_days=ALL_ON)  # 11-01 에 만든 습관(매일)
    clock(2, 9, 0)
    _entry(client, a, item["id"], done=True)  # 11-02 기록 줄이 생긴다
    clock(3, 9, 0)
    r = client.put(f"/schedule/check/items/{item['id']}", json={"repeat_days": TUE_OFF}, headers=a)
    assert r.status_code == 200 and r.json()["applies"] is False  # 오늘(화)은 새 요일

    assert _db_item(item["id"]).repeat_updated_at is not None
    # 변경 전날: 줄이 있으니 켜짐, 줄이 없는 날은 꺼짐
    assert _applies(client, a, item["id"], date(2026, 11, 2)) is True
    assert _applies(client, a, item["id"], date(2026, 11, 1)) is False

    clock(4, 9, 0)  # 다음 날(수): 새 패턴
    assert _applies(client, a, item["id"], date(2026, 11, 3)) is False  # 변경일 이후 화요일 꺼짐
    assert _applies(client, a, item["id"]) is True  # 수요일은 켜짐


def test_applies_is_false_before_item_created_day(client, family, clock):
    """습관을 만든 날보다 앞선 날짜는 요일이 맞아도 applies 가 거짓이다(그 날은 기록도 400)."""
    a, _, _ = family
    clock(3, 9, 0)
    item = _made(client, a, repeat_days=ALL_ON)  # 11-03 에 만든 습관(매일)
    assert _applies(client, a, item["id"]) is True  # 만든 날
    assert _applies(client, a, item["id"], date(2026, 11, 2)) is False  # 만들기 전날
    assert _applies(client, a, item["id"], date(2026, 10, 30)) is False
    r = client.put(f"/schedule/check/items/{item['id']}/entry?date=2026-11-02", json={"done": True}, headers=a)
    assert r.status_code == 400


def test_name_only_or_same_value_keeps_repeat_updated_at(client, family, clock):
    a, _, _ = family
    clock(1, 9, 0)
    item = _made(client, a, repeat_days=ALL_ON)
    clock(3, 9, 0)
    client.put(f"/schedule/check/items/{item['id']}", json={"repeat_days": TUE_OFF}, headers=a)
    stamp = _db_item(item["id"]).repeat_updated_at
    assert stamp is not None

    clock(5, 9, 0)
    client.put(
        f"/schedule/check/items/{item['id']}",
        json={"name": "바뀐 이름", "shared": False, "notify": True},
        headers=a,
    )
    assert _db_item(item["id"]).repeat_updated_at == stamp  # 이름·공개·알림만 바꾸면 불변

    client.put(f"/schedule/check/items/{item['id']}", json={"repeat_days": TUE_OFF}, headers=a)
    assert _db_item(item["id"]).repeat_updated_at == stamp  # 같은 값으로 저장해도 불변
    assert _db_item(item["id"]).repeat_days == TUE_OFF


def test_repeat_changed_again_same_day_updates_value(client, family, clock):
    a, _, _ = family
    clock(1, 9, 0)
    item = _made(client, a, repeat_days=ALL_ON)
    clock(3, 9, 0)
    client.put(f"/schedule/check/items/{item['id']}", json={"repeat_days": TUE_OFF}, headers=a)
    client.put(f"/schedule/check/items/{item['id']}", json={"repeat_days": SUN_OFF}, headers=a)
    row = _db_item(item["id"])
    assert row.repeat_days == SUN_OFF and row.repeat_updated_at is not None
    assert _applies(client, a, item["id"]) is True  # 11-03(화) 는 새 패턴(일만 꺼짐)


def test_family_view_uses_current_pattern(client, family, clock):
    a, b, _ = family
    clock(1, 9, 0)
    item = _made(client, b, name="안부 전화", repeat_days=ALL_ON)
    clock(3, 9, 0)
    client.put(f"/schedule/check/items/{item['id']}", json={"repeat_days": TUE_OFF}, headers=b)
    b_id = _me(client, b)
    view = client.get(f"/schedule/check/members/{b_id}/today", headers=a).json()
    assert view["items"] == []  # 오늘(화) 꺼진 현재 패턴
    summary = {
        row["name"]: row for row in client.get("/schedule/check/members/summary", headers=a).json()
    }
    assert summary["수진"]["total"] == 0


def test_new_item_has_no_repeat_updated_at(client, family, clock):
    a, _, _ = family
    item = _made(client, a)
    assert _db_item(item["id"]).repeat_updated_at is None
    assert item["applies"] is True


# ---------------------------------------------------------------- 습관 수정 시각(updated_at)
def test_name_change_updates_updated_at_not_repeat(client, family, clock):
    a, _, _ = family
    clock(1, 9, 0)
    item = _made(client, a, repeat_days=ALL_ON)
    created = _db_item(item["id"]).updated_at
    clock(2, 9, 0)
    client.put(f"/schedule/check/items/{item['id']}", json={"name": "새 이름"}, headers=a)
    row = _db_item(item["id"])
    assert row.updated_at != created and row.updated_at is not None
    assert row.repeat_updated_at is None  # 이름만 바꾸면 요일 변경 시각은 그대로


def test_repeat_change_updates_both_timestamps(client, family, clock):
    a, _, _ = family
    clock(1, 9, 0)
    item = _made(client, a, repeat_days=ALL_ON)
    clock(3, 9, 0)
    client.put(f"/schedule/check/items/{item['id']}", json={"repeat_days": TUE_OFF}, headers=a)
    row = _db_item(item["id"])
    assert row.updated_at == row.repeat_updated_at  # 같은 시각(지금)으로 함께 갱신
    assert row.updated_at.replace(tzinfo=UTC).astimezone(KST).date() == date(2026, 11, 3)


def test_order_and_delete_do_not_touch_updated_at(client, family, clock):
    a, _, _ = family
    clock(1, 9, 0)
    first = _made(client, a, name="첫째")
    second = _made(client, a, name="둘째")
    before = {i: _db_item(i).updated_at for i in (first["id"], second["id"])}
    clock(2, 9, 0)
    r = client.put(
        "/schedule/check/items/order", json={"ids": [second["id"], first["id"]]}, headers=a
    )
    assert r.status_code == 200
    for item_id, stamp in before.items():
        assert _db_item(item_id).updated_at == stamp  # 순서만 바꾸면 불변
    clock(3, 9, 0)
    client.delete(f"/schedule/check/items/{first['id']}", headers=a)
    assert _db_item(first["id"]).updated_at == before[first["id"]]  # 삭제도 불변


def test_same_value_save_keeps_timestamps(client, family, clock):
    a, _, _ = family
    clock(1, 9, 0)
    item = _made(client, a, name="물", repeat_days=ALL_ON)
    before = _db_item(item["id"]).updated_at
    clock(2, 9, 0)
    client.put(
        f"/schedule/check/items/{item['id']}",
        json={"name": "물", "repeat_days": ALL_ON, "notify": False},
        headers=a,
    )
    row = _db_item(item["id"])
    assert row.updated_at == before and row.repeat_updated_at is None


def test_item_response_includes_updated_at(client, family, clock):
    a, _, _ = family
    made = _made(client, a)
    assert made["updated_at"] is not None
    assert _find(client, a, made["id"])["updated_at"] == made["updated_at"]
