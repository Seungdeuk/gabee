"""notify() 시험: 구성원에게만, 본인 행동 제외, 중복 제거, 실패 격리."""

import pytest
from sqlalchemy import select

from app.shared.db import SessionLocal
from app.shared.notifications import Notification, notify


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
