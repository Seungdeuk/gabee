"""정산 재알림: 보낼 돈 알림을 받은 지 24시간이 지나도 송금 완료가 안 됐으면, 홈을 연 본인 몫만 알림함에 한 번 남긴다."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.shared.config import settings
from app.shared.db import SessionLocal, engine
from app.shared.notifications import Notification

CHECK = "/billing/settlement/reminders/check"


def _expense(client, headers, month="2026-10"):
    r = client.post(
        "/billing/expenses",
        json={"title": "장보기", "amount": 10000, "date": f"{month}-12"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _settle(client, headers, month="2026-10"):
    eid = _expense(client, headers, month)
    r = client.post(
        "/billing/settlement/tag",
        json={"month": month, "expense_ids": [eid], "tag": "all"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _age(month, hours):
    """그 달 정산 알림을 hours 시간 전에 만든 것으로 돌린다(시간으로 도는 장치가 없어서 기록 시각을 옮긴다)."""
    with SessionLocal() as db:
        db.execute(
            update(Notification)
            .where(Notification.event == "settlement_pay", Notification.target_id == month)
            .values(created_at=datetime.now(UTC) - timedelta(hours=hours))
        )
        db.commit()


def _check(client, headers):
    r = client.post(CHECK, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["created"]


def _reminders(client, headers):
    items = client.get("/notifications", params={"kind": "billing"}, headers=headers).json()[
        "items"
    ]
    return [(n["event"], n["target_id"]) for n in items if n["event"] == "settlement_remind"]


def test_not_sent_before_the_wait_has_passed(client, family):
    a, b, _ = family  # a=지민(지출), b=수진(보낼 사람)
    _settle(client, a)
    _age("2026-10", settings.settlement_remind_hours - 1)  # 23시간 전
    assert _check(client, b) == 0
    assert _reminders(client, b) == []


def test_sent_once_after_the_wait_has_passed(client, family):
    a, b, _ = family
    _settle(client, a)
    _age("2026-10", settings.settlement_remind_hours + 1)  # 25시간 전
    assert _check(client, b) == 1
    assert _reminders(client, b) == [("settlement_remind", "2026-10")]
    assert _check(client, b) == 0  # 홈을 다시 열어도 두 번째는 만들지 않는다
    assert len(_reminders(client, b)) == 1
    (note,) = [
        n
        for n in client.get("/notifications", params={"kind": "billing"}, headers=b).json()["items"]
        if n["event"] == "settlement_remind"
    ]
    assert note["title"] == "정산 송금이 아직 남았어요"
    assert note["body"] == "2026-10 정산에서 보낼 돈이 있어요"
    assert not any(s in f"{note['title']}{note['body']}" for s in ("5,000", "5000", "원"))


def test_not_sent_after_the_payment_is_marked_done(client, family):
    a, b, _ = family
    result = _settle(client, a)
    _age("2026-10", settings.settlement_remind_hours + 1)
    (t,) = result["transfers"]
    r = client.post(
        "/billing/settlement/payments",
        json={
            "month": "2026-10",
            "from_user_id": t["from_user_id"],
            "to_user_id": t["to_user_id"],
            "amount": t["amount"],
        },
        headers=a,
    )
    assert r.status_code == 201, r.text
    assert _check(client, b) == 0
    assert _reminders(client, b) == []


def test_only_the_member_who_opened_home_and_only_the_overdue_month(client, family):
    a, b, _ = family
    _settle(client, a, "2026-09")
    _settle(client, a, "2026-10")
    _age("2026-10", settings.settlement_remind_hours + 1)  # 10월만 지났고 9월은 방금 정산했다
    assert _check(client, a) == 0  # 받을 사람(지출을 낸 지민)에게는 만들지 않는다
    assert (
        _reminders(client, b) == []
    )  # 수진이 홈을 열기 전에는 수진 몫도 만들지 않는다(가족 몫을 대신 만들지 않는다)
    assert _check(client, b) == 1
    assert _reminders(client, b) == [("settlement_remind", "2026-10")]  # 9월은 아직 아니다
    assert _reminders(client, a) == []


def test_missing_notifications_table_does_not_break_home(client, family):
    a, b, _ = family
    _settle(client, a)
    Notification.__table__.drop(engine)
    try:
        r = client.post(CHECK, headers=b)
        assert r.status_code == 200 and r.json() == {"created": 0}
    finally:
        Notification.__table__.create(engine)
    with SessionLocal() as db:  # 표가 다시 만들어져 다른 시험에 영향이 없다
        assert db.scalars(select(Notification)).all() == []
