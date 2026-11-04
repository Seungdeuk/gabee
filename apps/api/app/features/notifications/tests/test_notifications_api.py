"""내 알림 조회·읽음 API(/notifications) 시험."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.features.family_group.models import GroupMember
from app.shared.db import SessionLocal
from app.shared.notifications import Notification

BASE = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def family(client, family):
    """가족을 만들 때 생기는 가입 알림은 지우고 시작한다(이 시험은 알림 개수를 직접 센다)."""
    with SessionLocal() as db:
        db.execute(delete(Notification))
        db.commit()
    return family


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _make(user_id, group_id, title, kind="family_group", minutes=0, read=False) -> str:
    with SessionLocal() as db:
        row = Notification(
            user_id=user_id,
            group_id=group_id,
            kind=kind,
            event="test",
            title=title,
            created_at=BASE + timedelta(minutes=minutes),
            read_at=(BASE + timedelta(hours=1)) if read else None,
        )
        db.add(row)
        db.commit()
        return row.id


def test_requires_login(client):
    for method, path in (
        ("get", "/notifications"),
        ("get", "/notifications/unread-count"),
        ("post", "/notifications/x/read"),
        ("post", "/notifications/read-all"),
    ):
        assert getattr(client, method)(path).status_code == 401


def test_list_newest_first_and_paginates(client, family):
    a, _b, group = family
    me = _me(client, a)
    for i in range(5):
        _make(me, group["id"], f"알림{i}", minutes=i)
    seen, cursor = [], None
    for _ in range(3):
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = client.get("/notifications", params=params, headers=a).json()
        seen += [n["title"] for n in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == ["알림4", "알림3", "알림2", "알림1", "알림0"]
    assert cursor is None


def test_kind_filter_and_invalid_kind(client, family):
    a, _b, group = family
    me = _me(client, a)
    _make(me, group["id"], "일정", kind="schedule", minutes=1)
    _make(me, group["id"], "가계", kind="billing", minutes=2)
    only = client.get("/notifications", params={"kind": "schedule"}, headers=a).json()
    assert [n["title"] for n in only["items"]] == ["일정"]
    assert client.get("/notifications", params={"kind": "chat"}, headers=a).status_code == 422
    empty = client.get("/notifications", params={"kind": "care"}, headers=a).json()
    assert empty == {"items": [], "next_cursor": None}


def test_unread_count_by_kind(client, family):
    a, _b, group = family
    me = _me(client, a)
    first = _make(me, group["id"], "하나", kind="schedule", minutes=1)
    _make(me, group["id"], "둘", kind="schedule", minutes=2)
    _make(me, group["id"], "셋", kind="care", minutes=3)
    _make(me, group["id"], "읽음", kind="care", minutes=4, read=True)
    count = client.get("/notifications/unread-count", headers=a).json()
    assert count == {"total": 3, "by_kind": {"schedule": 2, "care": 1}}
    client.post(f"/notifications/{first}/read", headers=a)
    count = client.get("/notifications/unread-count", headers=a).json()
    assert count == {"total": 2, "by_kind": {"schedule": 1, "care": 1}}


def test_read_marks_and_is_idempotent(client, family):
    a, _b, group = family
    note = _make(_me(client, a), group["id"], "읽을 것")
    first = client.post(f"/notifications/{note}/read", headers=a)
    assert first.status_code == 200 and first.json()["read_at"] is not None
    again = client.post(f"/notifications/{note}/read", headers=a)
    assert again.status_code == 200
    assert again.json()["read_at"] == first.json()["read_at"]


def test_other_users_notification_is_404(client, family):
    a, b, group = family
    mine = _make(_me(client, a), group["id"], "내 것")
    assert client.post(f"/notifications/{mine}/read", headers=b).status_code == 404
    assert client.post("/notifications/nope/read", headers=a).status_code == 404
    assert client.get("/notifications", headers=b).json()["items"] == []
    assert client.get("/notifications/unread-count", headers=a).json()["total"] == 1


def test_read_all_optionally_by_kind(client, family):
    a, _b, group = family
    me = _me(client, a)
    _make(me, group["id"], "일정1", kind="schedule", minutes=1)
    _make(me, group["id"], "일정2", kind="schedule", minutes=2)
    _make(me, group["id"], "돌봄", kind="care", minutes=3)
    done = client.post("/notifications/read-all", json={"kind": "schedule"}, headers=a)
    assert done.status_code == 200 and done.json() == {"updated": 2}
    assert client.get("/notifications/unread-count", headers=a).json()["total"] == 1
    rest = client.post("/notifications/read-all", headers=a)
    assert rest.json() == {"updated": 1}
    assert client.get("/notifications/unread-count", headers=a).json()["total"] == 0


def test_left_group_notifications_hidden(client, family):
    a, b, group = family
    mine = _make(_me(client, b), group["id"], "탈퇴 전 알림")
    assert len(client.get("/notifications", headers=b).json()["items"]) == 1
    with SessionLocal() as db:  # 수진이 그룹에서 빠진 상태
        db.execute(
            delete(GroupMember).where(
                GroupMember.group_id == group["id"], GroupMember.user_id == _me(client, b)
            )
        )
        db.commit()
    assert client.get("/notifications", headers=b).json()["items"] == []
    assert client.get("/notifications/unread-count", headers=b).json()["total"] == 0
    assert client.post(f"/notifications/{mine}/read", headers=b).status_code == 404


def test_invalid_cursor_is_400(client, family):
    a, _b, _group = family
    res = client.get("/notifications", params={"cursor": "###"}, headers=a)
    assert res.status_code == 400
    assert res.json()["code"] == "invalid_cursor"


def test_personal_notification_is_visible_only_to_owner_and_survives_leaving_family(client, family):
    a, b, group = family
    me = _me(client, a)
    nid = _make(me, None, "문의에 답변이 달렸어요", kind="support")
    assert [n["title"] for n in client.get("/notifications", headers=a).json()["items"]] == [
        "문의에 답변이 달렸어요"
    ]
    assert client.get("/notifications/unread-count", headers=a).json()["by_kind"] == {"support": 1}
    assert (
        client.get("/notifications", headers=b).json()["items"] == []
    )  # 다른 사람에게는 안 보인다
    assert client.post(f"/notifications/{nid}/read", headers=b).status_code == 404
    with SessionLocal() as db:  # 가족을 떠나도 개인 알림은 그대로 보인다
        db.execute(
            delete(GroupMember).where(
                GroupMember.group_id == group["id"], GroupMember.user_id == me
            )
        )
        db.commit()
    assert len(client.get("/notifications", headers=a).json()["items"]) == 1
    assert client.post(f"/notifications/{nid}/read", headers=a).status_code == 200
    assert client.get("/notifications/unread-count", headers=a).json()["total"] == 0
