"""푸시 차단 규칙(방해금지·끈 분류·꺼짐)과 받는 사람 계산 시험."""

from datetime import UTC, datetime, time

from app.shared.db import SessionLocal
from app.shared.push import in_quiet_hours, plan_recipients
from app.shared.push_models import PushSetting, PushToken

# 한국 시간(UTC+9) 기준 시각을 UTC 로 만든다: 한국 23:30 = UTC 14:30
KST_2330 = datetime(2026, 11, 5, 14, 30, tzinfo=UTC)
KST_0630 = datetime(2026, 11, 5, 21, 30, tzinfo=UTC)  # 한국 11/6 06:30
KST_1200 = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _token(user_id: str, token: str) -> None:
    with SessionLocal() as db:
        db.add(PushToken(user_id=user_id, token=token, platform="android"))
        db.commit()


def _setting(user_id: str, **values) -> None:
    with SessionLocal() as db:
        db.add(PushSetting(user_id=user_id, **values))
        db.commit()


def _plan(user_ids, kind="schedule", now=KST_1200):
    with SessionLocal() as db:
        return plan_recipients(
            db, user_ids=user_ids, kind=kind, title="제목", body=None, data={"kind": kind}, now=now
        )


def test_quiet_hours_same_day():
    assert in_quiet_hours(KST_1200, time(9, 0), time(18, 0)) is True  # 한국 12:00
    assert in_quiet_hours(KST_2330, time(9, 0), time(18, 0)) is False  # 한국 23:30


def test_quiet_hours_cross_midnight():
    start, end = time(22, 0), time(7, 0)
    assert in_quiet_hours(KST_2330, start, end) is True
    assert in_quiet_hours(KST_0630, start, end) is True
    assert in_quiet_hours(KST_1200, start, end) is False
    assert (
        in_quiet_hours(datetime(2026, 11, 5, 22, 0, tzinfo=UTC), start, end) is False
    )  # 한국 07:00 은 끝(미포함)


def test_quiet_hours_none():
    assert in_quiet_hours(KST_2330, None, None) is False
    assert in_quiet_hours(KST_2330, time(22, 0), None) is False


def test_plan_default_settings_when_no_row(client, family):
    a, _b, _group = family
    me = _me(client, a)
    _token(me, "ExponentPushToken[a1]")
    [row] = _plan([me])
    assert row["user_id"] == me and row["token"] == "ExponentPushToken[a1]"
    assert row["title"] == "제목" and row["body"] is None and row["data"] == {"kind": "schedule"}


def test_plan_skips_disabled_muted_and_quiet(client, family):
    a, b, group = family
    me_a, me_b = _me(client, a), _me(client, b)
    _token(me_a, "ExponentPushToken[a1]")
    _token(me_b, "ExponentPushToken[b1]")
    _setting(me_a, enabled=False)
    assert _plan([me_a, me_b])[0]["user_id"] == me_b
    with SessionLocal() as db:  # a 는 다시 켜고 일정 분류만 끈다
        row = db.get(PushSetting, me_a)
        row.enabled, row.muted_kinds = True, ["schedule"]
        db.commit()
    assert [p["user_id"] for p in _plan([me_a, me_b])] == [me_b]
    assert [p["user_id"] for p in _plan([me_a, me_b], kind="billing")] == [me_a, me_b]
    with SessionLocal() as db:  # b 는 방해금지(22:00~07:00)
        db.add(PushSetting(user_id=me_b, quiet_start=time(22, 0), quiet_end=time(7, 0)))
        db.commit()
    assert [p["user_id"] for p in _plan([me_b], now=KST_2330)] == []
    assert [p["user_id"] for p in _plan([me_b], now=KST_1200)] == [me_b]


def test_plan_one_row_per_device_and_dedupes(client, family):
    a, _b, _group = family
    me = _me(client, a)
    _token(me, "ExponentPushToken[a1]")
    _token(me, "ExponentPushToken[a2]")
    rows = _plan([me, me])  # 같은 사용자를 두 번 넘겨도
    assert sorted(r["token"] for r in rows) == ["ExponentPushToken[a1]", "ExponentPushToken[a2]"]


def test_plan_user_without_token_gets_nothing(client, family):
    a, _b, _group = family
    assert _plan([_me(client, a)]) == []
