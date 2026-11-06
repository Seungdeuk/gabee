"""예약 푸시: 일정 시작 30분 전, 할 일 마감 당일 아침 9시. 서버가 주기적으로 "곧 시작하는 일정"을 직접 찾아 보내므로
일정을 고치거나 지워도 따로 고칠 예약이 없고, 같은 푸시는 보냈음 기록(고유 키)으로 한 번만 간다. 문구는 고정이라 내용을 싣지 않는다."""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.features.schedule.models import Event
from app.features.schedule.timeutil import local_tz
from app.shared import push, push_schedule
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
        start_time=None if all_day else local.time().replace(tzinfo=None),
        **over,
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
    _event(uid, group["id"], NOW + timedelta(minutes=20), all_day=True)  # 시간이 없는 종일 일정
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


def test_todo_due_today_pushes_a_fixed_text_at_9am_once(client, home, sent):
    a, _, group = home
    uid = _me(client, a)
    morning = datetime(2026, 11, 10, 9, 0, tzinfo=KST)
    _event(uid, group["id"], morning + timedelta(hours=9), kind=2, all_day=True, title="비밀 할 일")
    assert _run(morning - timedelta(minutes=1)) == 0  # 9시 전에는 보내지 않는다
    assert _run(morning) == 1
    [msg] = sent()
    assert msg["title"] == "오늘까지인 할 일이 있어요"
    assert msg["data"] == {"kind": "schedule", "event": "todo_due"}
    assert "비밀 할 일" not in str(msg)
    assert _run(morning + timedelta(hours=3)) == 0  # 같은 날 다시 보내지 않는다
    assert len(sent()) == 1


def test_finished_or_other_day_todos_do_not_push(client, home, sent):
    a, _, group = home
    uid = _me(client, a)
    morning = datetime(2026, 11, 10, 9, 0, tzinfo=KST)
    _event(uid, group["id"], morning, kind=2, all_day=True, checked=True)  # 이미 끝낸 할 일
    _event(uid, group["id"], morning + timedelta(days=1), kind=2, all_day=True)  # 내일 할 일
    assert _run(morning) == 0 and sent() == []


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
