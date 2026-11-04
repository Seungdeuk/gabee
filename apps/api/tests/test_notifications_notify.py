"""notify() 시험: 구성원에게만, 본인 행동 제외, 중복 제거, 실패 격리."""

import pytest
from sqlalchemy import delete, select

from app.shared.db import SessionLocal
from app.shared.notifications import Notification, notify


@pytest.fixture
def family(client, family):
    """가족을 만들 때 생기는 가입 알림은 지우고 시작한다(이 시험은 알림 개수를 직접 센다)."""
    with SessionLocal() as db:
        db.execute(delete(Notification))
        db.commit()
    return family


def _id(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _rows(db):
    return db.scalars(select(Notification)).all()


def _send(db, group_id, recipients, **kw):
    args = dict(
        group_id=group_id,
        kind="family_group",
        event="join_requested",
        recipients=recipients,
        title="가족 그룹 참여 요청이 왔어요",
    )
    args.update(kw)
    return notify(db, **args)


def test_creates_one_row_per_member_recipient(client, family, other_family):
    a, b, group = family
    ids = [_id(client, a), _id(client, b), _id(client, other_family)]  # 마지막은 비구성원
    with SessionLocal() as db:
        assert _send(db, group["id"], ids) == 2
        db.commit()
        assert {r.user_id for r in _rows(db)} == set(ids[:2])


def test_excludes_actor(client, family):
    a, b, group = family
    ids = [_id(client, a), _id(client, b)]
    with SessionLocal() as db:
        assert _send(db, group["id"], ids, actor_user_id=ids[0]) == 1
        db.commit()
        assert [r.user_id for r in _rows(db)] == [ids[1]]


def test_dedupes_recipients(client, family):
    a, _b, group = family
    me = _id(client, a)
    with SessionLocal() as db:
        assert _send(db, group["id"], [me, me]) == 1
        db.commit()
        assert len(_rows(db)) == 1


def test_unknown_kind_raises_value_error(client, family):
    a, _b, group = family
    with SessionLocal() as db, pytest.raises(ValueError):
        _send(db, group["id"], [_id(client, a)], kind="chat")


def test_failure_is_isolated(client, family, monkeypatch):
    a, b, group = family
    ids = [_id(client, a), _id(client, b)]
    with SessionLocal() as db:
        db.add(
            Notification(
                user_id=ids[0], group_id=group["id"], kind="care", event="x", title="먼저 있던 행"
            )
        )
        real_add = db.add

        def boom(obj):
            if isinstance(obj, Notification) and obj.title != "먼저 있던 행":
                raise RuntimeError("저장 실패")
            return real_add(obj)

        monkeypatch.setattr(db, "add", boom)
        assert _send(db, group["id"], ids) == 0  # 예외가 밖으로 나오지 않는다
        db.commit()
        assert [r.title for r in _rows(db)] == ["먼저 있던 행"]  # 앞선 변경은 그대로 저장된다


def test_personal_notification_has_no_group_and_skips_membership(client, family, other_family):
    outsider = _id(
        client, other_family
    )  # 어느 가족의 구성원이어도 아니어도 개인 알림은 본인에게 간다
    with SessionLocal() as db:
        created = notify(
            db,
            group_id=None,
            kind="support",
            event="ticket_answered",
            recipients=[outsider, outsider],
            title="문의에 답변이 달렸어요",
        )
        db.commit()
        assert created == 1  # 같은 사람은 한 번만
        assert [(r.user_id, r.group_id, r.kind) for r in _rows(db)] == [(outsider, None, "support")]
