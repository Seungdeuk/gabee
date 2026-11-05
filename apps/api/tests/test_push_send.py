"""푸시 발송: 커밋 뒤에만, 제목만, 실패 격리, 만료 토큰 정리."""

import pytest
from sqlalchemy import delete, select, text

from app.shared import push
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.notifications import Notification, notify
from app.shared.push_models import PushToken


@pytest.fixture
def family(client, family):
    """가족을 만들 때 생기는 가입 알림은 지우고 시작한다."""
    with SessionLocal() as db:
        db.execute(delete(Notification))
        db.commit()
    return family


@pytest.fixture
def sent(monkeypatch):
    """발송을 켜고, 스레드 대신 그 자리에서 실행하고, Expo 호출을 가짜로 바꾼다. 보낸 메시지 묶음 목록을 돌려준다."""
    batches: list[list[dict]] = []

    def fake_post(messages):
        batches.append(messages)
        return {"data": [{"status": "ok", "id": f"t{i}"} for i, _ in enumerate(messages)]}

    monkeypatch.setattr(settings, "push_enabled", True)
    monkeypatch.setattr(push, "_submit", lambda fn, *args: fn(*args))
    monkeypatch.setattr(push, "_post", fake_post)
    return batches


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _token(user_id: str, token: str) -> None:
    with SessionLocal() as db:
        db.add(PushToken(user_id=user_id, token=token, platform="android"))
        db.commit()


def _notify(db, group_id, recipients, **over):
    args = dict(
        group_id=group_id,
        kind="schedule",
        event="request_received",
        recipients=recipients,
        title="같이해요가 도착했어요",
    )
    args.update(over)
    return notify(db, **args)


def _flat(batches):
    return [m for batch in batches for m in batch]


def test_push_sent_only_after_commit(client, family, sent):
    a, b, group = family
    _token(_me(client, b), "ExponentPushToken[b1]")
    with SessionLocal() as db:
        _notify(db, group["id"], [_me(client, b)])
        assert sent == []  # 커밋 전에는 나가지 않는다
        db.commit()
    [msg] = _flat(sent)
    assert msg["to"] == "ExponentPushToken[b1]" and msg["title"] == "같이해요가 도착했어요"
    assert msg["channelId"] == "default" and msg["priority"] == "high"


def test_no_push_on_rollback(client, family, sent):
    _a, b, group = family
    _token(_me(client, b), "ExponentPushToken[b1]")
    with SessionLocal() as db:
        _notify(db, group["id"], [_me(client, b)])
        db.rollback()
        db.commit()
    assert sent == []


def test_push_title_only_and_navigation_data(client, family, sent):
    _a, b, group = family
    me_b = _me(client, b)
    _token(me_b, "ExponentPushToken[b1]")
    with SessionLocal() as db:
        _notify(db, group["id"], [me_b], target_type="schedule_request", target_id="r1")
        db.commit()
        row = db.scalars(select(Notification)).one()
    [msg] = _flat(sent)
    assert "body" not in msg  # 본문은 보내지 않는다
    assert msg["data"] == {
        "notification_id": row.id,
        "kind": "schedule",
        "event": "request_received",
        "target_type": "schedule_request",
        "target_id": "r1",
    }


def test_actor_not_pushed(client, family, sent):
    a, b, group = family
    me_a, me_b = _me(client, a), _me(client, b)
    _token(me_a, "ExponentPushToken[a1]")
    _token(me_b, "ExponentPushToken[b1]")
    with SessionLocal() as db:
        _notify(db, group["id"], [me_a, me_b], actor_user_id=me_a)
        db.commit()
    assert [m["to"] for m in _flat(sent)] == ["ExponentPushToken[b1]"]


def test_two_devices_two_messages(client, family, sent):
    _a, b, group = family
    me_b = _me(client, b)
    _token(me_b, "ExponentPushToken[b1]")
    _token(me_b, "ExponentPushToken[b2]")
    with SessionLocal() as db:
        _notify(db, group["id"], [me_b])
        db.commit()
    assert sorted(m["to"] for m in _flat(sent)) == [
        "ExponentPushToken[b1]",
        "ExponentPushToken[b2]",
    ]


def test_personal_notification_pushed(client, family, sent):
    a, _b, _group = family
    me_a = _me(client, a)
    _token(me_a, "ExponentPushToken[a1]")
    with SessionLocal() as db:
        notify(
            db,
            group_id=None,
            kind="support",
            event="ticket_answered",
            recipients=[me_a],
            title="문의에 답변이 달렸어요",
        )
        db.commit()
    assert [m["title"] for m in _flat(sent)] == ["문의에 답변이 달렸어요"]


def test_device_not_registered_deletes_token(client, family, monkeypatch, sent):
    _a, b, group = family
    me_b = _me(client, b)
    _token(me_b, "ExponentPushToken[dead]")
    _token(me_b, "ExponentPushToken[live]")

    def fake_post(messages):
        return {
            "data": [
                {"status": "error", "details": {"error": "DeviceNotRegistered"}}
                if m["to"].endswith("[dead]")
                else {"status": "ok", "id": "x"}
                for m in messages
            ]
        }

    monkeypatch.setattr(push, "_post", fake_post)
    with SessionLocal() as db:
        _notify(db, group["id"], [me_b])
        db.commit()
    with SessionLocal() as db:
        left = [r.token for r in db.scalars(select(PushToken))]
    assert left == ["ExponentPushToken[live]"]


@pytest.mark.parametrize("failure", ["timeout", "garbage", "wrong_length"])
def test_expo_failure_is_swallowed(client, family, monkeypatch, sent, failure):
    _a, b, group = family
    me_b = _me(client, b)
    _token(me_b, "ExponentPushToken[b1]")

    def broken(messages):
        if failure == "timeout":
            raise TimeoutError("expo down")
        return {"nope": 1} if failure == "garbage" else {"data": []}

    monkeypatch.setattr(push, "_post", broken)
    with SessionLocal() as db:
        _notify(db, group["id"], [me_b])
        db.commit()  # 푸시가 실패해도 커밋과 알림함 저장은 성공한다
    with SessionLocal() as db:
        assert len(db.scalars(select(Notification)).all()) == 1
        assert [r.token for r in db.scalars(select(PushToken))] == ["ExponentPushToken[b1]"]


def test_disabled_flag_sends_nothing(client, family, sent, monkeypatch):
    _a, b, group = family
    _token(_me(client, b), "ExponentPushToken[b1]")
    monkeypatch.setattr(settings, "push_enabled", False)
    with SessionLocal() as db:
        _notify(db, group["id"], [_me(client, b)])
        db.commit()
    assert sent == []


def test_missing_push_tables_does_not_break_notify(client, family, sent):
    _a, b, group = family
    with SessionLocal() as db:
        db.execute(text("DROP TABLE push_tokens"))
        db.execute(text("DROP TABLE push_settings"))
        db.commit()
    with SessionLocal() as db:
        assert _notify(db, group["id"], [_me(client, b)]) == 1
        db.commit()
        assert len(db.scalars(select(Notification)).all()) == 1
    assert sent == []


def test_push_only_sends_without_inbox_row(client, family, sent):
    _a, b, _group = family
    me_b = _me(client, b)
    _token(me_b, "ExponentPushToken[b1]")
    with SessionLocal() as db:
        push.push_only(
            db, user_ids=[me_b], kind="schedule", title="제목", body=None, data={"kind": "chat"}
        )
        db.commit()
        assert db.scalars(select(Notification)).all() == []  # 알림함에는 남기지 않는다
    assert [m["title"] for m in _flat(sent)] == ["제목"]


def test_two_notifies_in_one_request_push_only_after_final_commit(client, family, sent):
    """같은 요청에서 notify() 를 두 번 불러도(저장점이 두 번 열리고 닫혀도) 푸시는 마지막 커밋 뒤에만 나간다."""
    a, b, group = family
    me_a, me_b = _me(client, a), _me(client, b)
    _token(me_a, "ExponentPushToken[a1]")
    _token(me_b, "ExponentPushToken[b1]")
    with SessionLocal() as db:
        _notify(db, group["id"], [me_a], title="첫째")
        _notify(db, group["id"], [me_b], title="둘째")
        assert sent == []  # 저장점이 닫혔을 뿐 바깥 커밋은 아직이다
        db.commit()
    assert sorted(m["title"] for m in _flat(sent)) == ["둘째", "첫째"]


def test_savepoint_rollback_does_not_drop_pending_push(client, family, sent):
    """notify() 뒤에 다른 저장점이 롤백돼도 이미 쌓은 푸시는 바깥 커밋 때 나간다."""
    _a, b, group = family
    me_b = _me(client, b)
    _token(me_b, "ExponentPushToken[b1]")
    with SessionLocal() as db:
        _notify(db, group["id"], [me_b])
        try:
            with db.begin_nested():
                raise ValueError("저장점 안에서 실패")
        except ValueError:
            pass
        db.commit()
    assert [m["to"] for m in _flat(sent)] == ["ExponentPushToken[b1]"]


def test_outer_rollback_after_savepoints_sends_nothing(client, family, sent):
    """저장점이 정상으로 닫힌 뒤 바깥 트랜잭션이 롤백되면 푸시도 알림도 없다."""
    a, b, group = family
    me_a, me_b = _me(client, a), _me(client, b)
    _token(me_a, "ExponentPushToken[a1]")
    _token(me_b, "ExponentPushToken[b1]")
    with SessionLocal() as db:
        # 실제 요청처럼 알림보다 먼저 쓴 내용이 있어야 SQLite 가 바깥 트랜잭션을 연다(pysqlite 는 첫 SQL 이
        # SAVEPOINT 면 그 해제를 진짜 커밋으로 처리한다). PostgreSQL 에서는 이 준비 없이도 같다.
        db.add(PushToken(user_id=me_a, token="ExponentPushToken[tmp]", platform="android"))
        db.flush()
        _notify(db, group["id"], [me_a])
        _notify(db, group["id"], [me_b])
        db.rollback()
        db.commit()
    assert sent == []
    with SessionLocal() as db:
        assert db.scalars(select(Notification)).all() == []
