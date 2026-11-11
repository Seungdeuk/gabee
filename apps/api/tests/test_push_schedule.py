"""예약 푸시(2026-11-11 규칙): 약속·할 일 모두 **시간이 있으면 시작 30분 전**, **시간이 없으면(종일 포함) 전날 저녁 9시에 한 번**.
서버가 주기적으로 알릴 항목을 직접 찾아 보내므로 일정을 고치거나 지워도 따로 고칠 예약이 없고, 같은 푸시는 보냈음 기록(고유 키)으로
한 번만 간다. 문구는 고정이라 내용을 싣지 않는다."""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import func, select

from app.features.schedule import push_schedule
from app.features.schedule.models import Event
from app.features.schedule.timeutil import local_tz
from app.shared import push
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.push_models import PushToken, ScheduledPushLog

KST = local_tz()
NOW = datetime(2026, 11, 10, 10, 0, tzinfo=KST)  # 화요일 오전 10시
EVENT_TITLE = "일정 30분 전 알림"


@pytest.fixture
def sent(monkeypatch):
    batches: list[list[dict]] = []

    def fake_post(messages):
        batches.append(messages)
        return {"data": [{"status": "ok", "id": f"t{i}"} for i, _ in enumerate(messages)]}

    monkeypatch.setattr(settings, "push_enabled", True)
    monkeypatch.setattr(push, "_submit", lambda fn, *args: fn(*args))
    monkeypatch.setattr(push, "_post", fake_post)
    return lambda: [m for batch in batches for m in batch]


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _token(user_id: str, token: str) -> None:
    with SessionLocal() as db:
        db.add(PushToken(user_id=user_id, token=token, platform="android"))
        db.commit()


@pytest.fixture
def home(client, family):
    a, b, group = family
    for name, headers in (("a", a), ("b", b)):
        _token(_me(client, headers), f"ExponentPushToken[{name}]")
    return a, b, group


def _event(user_id, group_id, start: datetime, *, kind=1, all_day=False, title=EVENT_TITLE, **over):
    """일정 한 줄을 DB 에 직접 만든다(시간은 KST 로 날짜·시간에 나눠 넣는다)."""
    local = start.astimezone(KST)
    row = Event(
        id=uuid.uuid4().hex[:12],
        group_id=group_id,
        user_id=user_id,
        created_by=user_id,
        title=title,
        starts_at=start,
        kind=kind,
        start_date=local.date(),
        # 종일은 앱이 00:00~23:59 로 저장한다(시간 칸이 비어 있지 않다)
        **{
            "start_time": time(0, 0) if all_day else local.time().replace(tzinfo=None),
            "end_time": time(23, 59) if all_day else None,
            **over,
        },
    )
    with SessionLocal() as db:
        db.add(row)
        db.commit()
    return row.id


def _run(now=NOW) -> int:
    with SessionLocal() as db:
        return push_schedule.run_due(db, now)


def _tokens(pushes):
    return sorted(m["to"] for m in pushes)


def test_event_starting_in_30_minutes_pushes_a_fixed_text_to_its_owner(client, home, sent):
    a, b, group = home
    _event(_me(client, a), group["id"], NOW + timedelta(minutes=20))
    assert _run() == 1
    [msg] = sent()
    assert msg["to"] == "ExponentPushToken[a]"  # 일정 줄의 주인만(b 는 받지 않는다)
    assert msg["title"] == "30분 안에 시작하는 일정이 있어요" and not msg.get("body")
    assert msg["data"] == {"kind": "schedule", "event": "event_soon"}
    assert EVENT_TITLE not in str(msg)  # 일정 제목·장소를 싣지 않는다


def test_events_outside_the_window_do_not_push(client, home, sent):
    a, _, group = home
    uid = _me(client, a)
    _event(uid, group["id"], NOW + timedelta(minutes=45))  # 아직 멀다
    _event(uid, group["id"], NOW - timedelta(minutes=5))  # 이미 시작했다
    _event(uid, group["id"], NOW + timedelta(minutes=20), all_day=True)  # 종일 일정(00:00~23:59)
    assert _run() == 0 and sent() == []


def test_the_same_event_is_pushed_only_once_even_if_checked_again(client, home, sent):
    a, _, group = home
    _event(_me(client, a), group["id"], NOW + timedelta(minutes=25))
    assert _run() == 1
    assert _run(NOW + timedelta(minutes=1)) == 0  # 다음 확인에서도 같은 일정은 다시 보내지 않는다
    assert len(sent()) == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ScheduledPushLog)) == 1


def test_deleted_events_do_not_push(client, home, sent):
    a, _, group = home
    _event(_me(client, a), group["id"], NOW + timedelta(minutes=20), deleted_at=NOW)
    assert _run() == 0 and sent() == []


def test_moving_the_start_time_makes_a_new_push_for_the_new_time(client, home, sent):
    a, _, group = home
    eid = _event(_me(client, a), group["id"], NOW + timedelta(minutes=20))
    assert _run() == 1
    new_start = NOW + timedelta(minutes=50)  # 일정을 뒤로 옮겼다
    with SessionLocal() as db:
        row = db.get(Event, eid)
        row.starts_at = new_start
        row.start_time = new_start.astimezone(KST).time().replace(tzinfo=None)
        db.commit()
    assert _run(NOW + timedelta(minutes=25)) == 1  # 새 시작 30분 전
    assert len(sent()) == 2


def test_several_events_in_a_row_push_once_per_person(client, home, sent):
    a, _, group = home
    uid = _me(client, a)
    for minutes in (10, 20, 25):
        _event(uid, group["id"], NOW + timedelta(minutes=minutes))
    assert _run() == 3  # 세 일정을 모두 보냈음으로 기록하되
    assert len(sent()) == 1  # 푸시는 한 번만


def test_user_push_settings_still_apply(client, home, sent):
    a, _, group = home
    assert (
        client.put(
            "/notifications/push-settings", json={"muted_kinds": ["schedule"]}, headers=a
        ).status_code
        == 200
    )
    _event(_me(client, a), group["id"], NOW + timedelta(minutes=20))
    _run()
    assert sent() == []  # 일정 푸시를 끈 사람에게는 가지 않는다


def test_nothing_runs_when_push_is_disabled(client, home, monkeypatch):
    a, _, group = home
    _event(_me(client, a), group["id"], NOW + timedelta(minutes=20))
    monkeypatch.setattr(settings, "push_enabled", False)
    assert _run() == 0
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(ScheduledPushLog)) == 0


def test_tick_swallows_errors_so_the_loop_keeps_running(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("db gone")

    monkeypatch.setattr(push_schedule, "run_due", boom)
    push_schedule.tick()  # 예외가 밖으로 나오지 않는다


def test_an_event_that_starts_at_midnight_is_still_pushed_when_it_is_not_all_day(
    client, home, sent
):
    a, _, group = home
    start = datetime(2026, 11, 11, 0, 10, tzinfo=KST)
    _event(_me(client, a), group["id"], start, end_time=time(1, 0))  # 00:10~01:00 약속
    assert _run(datetime(2026, 11, 10, 23, 45, tzinfo=KST)) == 1  # 전날 23:40 이후
    assert len(sent()) == 1


def test_window_edges_30_minutes_before_is_in_the_start_itself_is_out(client, home, sent):
    a, _, group = home
    uid = _me(client, a)
    start = NOW + timedelta(minutes=30)
    _event(uid, group["id"], start)
    assert _run(NOW - timedelta(seconds=1)) == 0  # 30분 1초 전
    assert _run(NOW) == 1  # 정확히 30분 전
    other = _event(uid, group["id"], NOW + timedelta(minutes=5))
    assert other and _run(NOW + timedelta(minutes=5)) == 0  # 시작 정각은 이미 시작한 것


def test_checked_appointments_and_people_who_left_the_family_are_skipped(client, home, sent):
    a, b, group = home
    uid, bid = _me(client, a), _me(client, b)
    _event(uid, group["id"], NOW + timedelta(minutes=20), checked=True)  # 이미 한 약속
    _event(bid, group["id"], NOW + timedelta(minutes=20))
    assert client.post("/family-group/groups/me/leave", headers=b).status_code == 204
    assert _run() == 0 and sent() == []  # 나간 사람의 일정은 알리지 않는다


def test_shared_copies_each_push_to_their_own_owner(client, home, sent):
    a, b, group = home
    start = NOW + timedelta(minutes=20)
    _event(_me(client, a), group["id"], start)
    _event(_me(client, b), group["id"], start)  # 공유 복사본은 받은 사람 몫의 줄이다
    assert _run() == 2
    assert _tokens(sent()) == ["ExponentPushToken[a]", "ExponentPushToken[b]"]


# ── 2026-11-11 규칙: 시간 있으면 30분 전, 없으면 전날 저녁 9시 한 번(약속·할 일 공통) ──

SOON_TODO_TITLE = "30분 뒤에 챙길 할 일이 있어요"
EVENING_TITLE = "내일 챙길 일정이 있어요"
EVE = datetime(2026, 11, 10, 21, 0, tzinfo=KST)  # 화요일 저녁 9시 → 내일(수요일) 항목을 알린다
TOMORROW = datetime(2026, 11, 11, 0, 0, tzinfo=KST)


def _notimed(user_id, group_id, day: datetime, *, kind=1, all_day=True, **over):
    """시간이 없는 항목: 종일(00:00~23:59) 또는 시간 칸이 빈 것."""
    # 시험의 "지금"(2026-11-10)은 실제 오늘보다 이르다: 만든 시각을 안 정하면 실제 지금이 들어가 "저녁 전에 만든 것만" 규칙에 걸린다
    over.setdefault("created_at", EVE - timedelta(days=2))
    if all_day:
        return _event(user_id, group_id, day, kind=kind, all_day=True, **over)
    return _event(user_id, group_id, day, kind=kind, start_time=None, end_time=None, **over)


def test_timed_todo_pushes_30_minutes_before_with_its_own_fixed_text(client, home, sent):
    a, _, group = home
    _event(_me(client, a), group["id"], NOW + timedelta(minutes=20), kind=2, title="비밀 할 일")
    assert _run() == 1
    [msg] = sent()
    assert msg["title"] == SOON_TODO_TITLE and not msg.get("body")
    assert msg["data"] == {"kind": "schedule", "event": "todo_soon"}
    assert "비밀 할 일" not in str(msg)


def test_timed_todo_window_is_30_minutes_before_up_to_the_start(client, home, sent):
    a, _, group = home
    uid = _me(client, a)
    _event(uid, group["id"], NOW + timedelta(minutes=45), kind=2)  # 아직 멀다
    _event(uid, group["id"], NOW - timedelta(minutes=5), kind=2)  # 이미 시작했다
    assert _run() == 0 and sent() == []
    start = NOW + timedelta(minutes=30)
    _event(uid, group["id"], start, kind=2)
    assert _run(NOW - timedelta(seconds=1)) == 0  # 30분 1초 전
    assert _run(NOW) == 1  # 정확히 30분 전


def test_checked_deleted_and_left_timed_todos_do_not_push(client, home, sent):
    a, b, group = home
    uid, bid = _me(client, a), _me(client, b)
    _event(uid, group["id"], NOW + timedelta(minutes=20), kind=2, checked=True)
    _event(uid, group["id"], NOW + timedelta(minutes=20), kind=2, deleted_at=NOW)
    _event(bid, group["id"], NOW + timedelta(minutes=20), kind=2)
    assert client.post("/family-group/groups/me/leave", headers=b).status_code == 204
    assert _run() == 0 and sent() == []


def test_the_same_timed_todo_is_pushed_only_once(client, home, sent):
    a, _, group = home
    _event(_me(client, a), group["id"], NOW + timedelta(minutes=25), kind=2)
    assert _run() == 1
    assert _run(NOW + timedelta(minutes=1)) == 0 and len(sent()) == 1


@pytest.mark.parametrize("kind", [1, 2])
@pytest.mark.parametrize("all_day", [True, False])
def test_untimed_item_pushes_once_the_evening_before_for_both_kinds(
    client, home, sent, kind, all_day
):
    a, _, group = home
    _notimed(_me(client, a), group["id"], TOMORROW, kind=kind, all_day=all_day, title="비밀 항목")
    assert _run(EVE - timedelta(minutes=1)) == 0  # 저녁 9시 전에는 보내지 않는다
    assert _run(EVE) == 1
    [msg] = sent()
    assert msg["to"] == "ExponentPushToken[a]"  # 항목 줄의 주인만
    assert msg["title"] == EVENING_TITLE and not msg.get("body")
    assert msg["data"] == {"kind": "schedule", "event": "evening_before"}
    assert "비밀 항목" not in str(msg)
    assert (
        _run(EVE + timedelta(hours=3)) == 0 and len(sent()) == 1
    )  # 같은 날 저녁 다시 보내지 않는다


def test_untimed_evening_push_is_not_sent_for_today_or_two_days_ahead(client, home, sent):
    a, _, group = home
    uid = _me(client, a)
    _notimed(
        uid, group["id"], EVE.replace(hour=0), kind=2
    )  # 오늘 항목: 전날이 없으니 알리지 않는다(옛 9시 알림 없음)
    _notimed(uid, group["id"], TOMORROW + timedelta(days=1), kind=2)  # 모레 항목
    assert _run(EVE) == 0 and sent() == []
    assert _run(EVE.replace(hour=9)) == 0 and sent() == []  # 오전 9시에도 아무것도 가지 않는다


def test_untimed_evening_window_closes_at_midnight(client, home, sent):
    a, _, group = home
    _notimed(_me(client, a), group["id"], TOMORROW, kind=1)
    assert _run(TOMORROW) == 0 and sent() == []  # 자정이 지나면 그날 항목은 더 알리지 않는다


def test_timed_items_are_not_pushed_in_the_evening(client, home, sent):
    a, _, group = home
    uid = _me(client, a)
    before = EVE - timedelta(days=2)  # 저녁 전에 만든 항목이라 "만든 시각" 규칙에 걸리지 않게 한다
    _event(uid, group["id"], TOMORROW.replace(hour=14), kind=1, created_at=before)
    _event(uid, group["id"], TOMORROW.replace(hour=15), kind=2, created_at=before)
    assert _run(EVE) == 0 and sent() == []  # 시간이 있으면 전날 저녁이 아니라 30분 전에만


def test_untimed_item_created_after_the_evening_is_not_pushed_right_away(client, home, sent):
    """밤 10시에 "내일 할 일"을 만든 사람에게 곧바로 "내일 챙길 일정"이 가면 소음이다."""
    a, _, group = home
    _notimed(
        _me(client, a),
        group["id"],
        TOMORROW,
        kind=2,
        created_at=(EVE + timedelta(hours=1)).astimezone(UTC),
    )  # 앱처럼 UTC 로 저장
    assert _run(EVE + timedelta(hours=2)) == 0 and sent() == []


def test_checked_deleted_untimed_and_left_members_are_skipped_in_the_evening(client, home, sent):
    a, b, group = home
    uid, bid = _me(client, a), _me(client, b)
    _notimed(uid, group["id"], TOMORROW, kind=1, checked=True)
    _notimed(uid, group["id"], TOMORROW, kind=2, deleted_at=EVE)
    _notimed(bid, group["id"], TOMORROW, kind=2)
    assert client.post("/family-group/groups/me/leave", headers=b).status_code == 204
    assert _run(EVE) == 0 and sent() == []


def test_several_untimed_items_push_once_per_person_and_shared_copies_each_push(client, home, sent):
    a, b, group = home
    ua, ub = _me(client, a), _me(client, b)
    for kind in (1, 2, 2):
        _notimed(ua, group["id"], TOMORROW, kind=kind)
    _notimed(ub, group["id"], TOMORROW, kind=1)  # 공유 복사본은 받은 사람 몫의 줄
    assert _run(EVE) == 4  # 모두 보냈음으로 기록하되
    assert _tokens(sent()) == [
        "ExponentPushToken[a]",
        "ExponentPushToken[b]",
    ]  # 푸시는 사람마다 한 번


def test_quiet_hours_do_not_use_up_the_evening_push_so_it_goes_out_later(client, home, sent):
    """방해금지(20:00~21:30)에 걸려 걸러진 저녁 알림은 기록을 남기지 않아, 끝난 뒤 다음 확인에서 간다."""
    a, _, group = home
    r = client.put(
        "/notifications/push-settings",
        json={"quiet_start": "20:00:00", "quiet_end": "21:30:00"},
        headers=a,
    )
    assert r.status_code == 200, r.text
    _notimed(_me(client, a), group["id"], TOMORROW, kind=2)
    assert _run(EVE) == 0 and sent() == []  # 방해금지 중: 보내지도 기록하지도 않는다
    assert _run(EVE + timedelta(minutes=40)) == 1  # 21:40, 방해금지가 끝났다
    assert len(sent()) == 1


def test_the_morning_9am_todo_push_no_longer_exists(client, home, sent):
    a, _, group = home
    today = datetime(2026, 11, 10, 9, 0, tzinfo=KST)
    _notimed(_me(client, a), group["id"], today, kind=2, created_at=today - timedelta(days=1))
    assert _run(today) == 0 and sent() == []
    assert not hasattr(push_schedule, "TODO_HOUR")


def test_an_untimed_item_is_not_pushed_as_30_minutes_before_the_night_before(client, home, sent):
    """종일 일정은 00:00~23:59 로 저장돼서 시작 시각만 보면 전날 23:30 에 "30분 안에 시작" 푸시가 갈 수 있다. 가는 것은 저녁 알림 한 번뿐이다."""
    a, _, group = home
    _notimed(_me(client, a), group["id"], TOMORROW, kind=1)
    assert _run(EVE) == 1  # 저녁 9시 알림
    assert _run(TOMORROW - timedelta(minutes=30)) == 0  # 23:30 에는 다시 보내지 않는다
    [msg] = sent()
    assert msg["title"] == EVENING_TITLE
