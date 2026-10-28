"""가입 요청·승인 때 알림함에 남는 알림 시험(kind=family_group)."""

from sqlalchemy import select, update

from app.features.family_group.models import GroupMember
from app.features.family_group.tests.test_join_approval import (
    P,
    account,
    create_group,
    join,
    new_code,
)
from app.shared.db import SessionLocal
from app.shared.notifications import Notification


def _notes(user_id):
    with SessionLocal() as db:
        rows = db.scalars(select(Notification).where(Notification.user_id == user_id)).all()
        return [(r.kind, r.event, r.target_type, r.actor_user_id) for r in rows]


def _make_member(client, owner, group, login_id, role="member"):
    """승인까지 마친 구성원을 만들고(role 이 admin 이면 DB 에서 올린다) (헤더, id)를 돌려준다."""
    headers, user_id = account(client, login_id)
    req = join(client, headers, new_code(client, owner)).json()
    assert (
        client.post(f"{P}/groups/join-requests/{req['id']}/approve", headers=owner).status_code
        == 200
    )
    if role != "member":
        with SessionLocal() as db:
            db.execute(
                update(GroupMember)
                .where(GroupMember.group_id == group["id"], GroupMember.user_id == user_id)
                .values(role=role)
            )
            db.commit()
    return headers, user_id


def test_request_notifies_all_managers_only(client):
    owner, owner_id = account(client, "owner_kim")
    group = create_group(client, owner)
    _admin, admin_id = _make_member(client, owner, group, "admin_park", role="admin")
    _member, member_id = _make_member(client, owner, group, "member_lee")
    owner_before = len(_notes(owner_id))
    admin_before = len(_notes(admin_id))

    guest, guest_id = account(client, "guest_choi")
    assert join(client, guest, new_code(client, owner)).status_code == 200

    assert len(_notes(owner_id)) == owner_before + 1
    assert len(_notes(admin_id)) == admin_before + 1
    assert _notes(member_id) == [] or all(
        e != "join_requested" for _k, e, _t, _a in _notes(member_id)
    )
    assert _notes(guest_id) == []
    last = [n for n in _notes(owner_id) if n[1] == "join_requested"][-1]
    assert last == ("family_group", "join_requested", "join_request", guest_id)


def test_duplicate_request_does_not_duplicate_notification(client):
    owner, owner_id = account(client, "owner_kim")
    group = create_group(client, owner)
    guest, _guest_id = account(client, "guest_choi")
    first = join(client, guest, new_code(client, owner)).json()
    # 같은 사람이 새 코드로 다시 신청해도 기존 대기 요청을 돌려주고 새 요청·알림은 만들지 않는다
    again = join(client, guest, new_code(client, owner)).json()
    assert first["id"] == again["id"]
    assert [n for n in _notes(owner_id) if n[1] == "join_requested"] == [
        ("family_group", "join_requested", "join_request", _guest_id)
    ]
    assert group["id"]


def test_approve_notifies_applicant(client):
    owner, owner_id = account(client, "owner_kim")
    group = create_group(client, owner)
    guest, guest_id = account(client, "guest_choi")
    req = join(client, guest, new_code(client, owner)).json()
    assert _notes(guest_id) == []  # 승인 전에는 아무 알림도 없다
    assert (
        client.post(f"{P}/groups/join-requests/{req['id']}/approve", headers=owner).status_code
        == 200
    )

    assert _notes(guest_id) == [("family_group", "join_approved", "group", owner_id)]
    listed = client.get("/notifications", headers=guest).json()["items"]
    assert [n["event"] for n in listed] == ["join_approved"]
    assert listed[0]["target_id"] == group["id"]


def test_reject_creates_no_notification(client):
    owner, _owner_id = account(client, "owner_kim")
    create_group(client, owner)
    guest, guest_id = account(client, "guest_choi")
    req = join(client, guest, new_code(client, owner)).json()
    assert (
        client.post(f"{P}/groups/join-requests/{req['id']}/reject", headers=owner).status_code
        == 204
    )
    assert _notes(guest_id) == []


def test_notify_failure_does_not_break_join(client, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("알림 저장 실패")

    monkeypatch.setattr("app.shared.notifications.Notification", boom)  # 알림 저장만 실패시킨다
    owner, owner_id = account(client, "owner_kim")
    create_group(client, owner)
    guest, guest_id = account(client, "guest_choi")
    req = join(client, guest, new_code(client, owner))
    assert req.status_code == 200 and req.json()["status"] == "pending"
    done = client.post(f"{P}/groups/join-requests/{req.json()['id']}/approve", headers=owner)
    assert done.status_code == 200
    assert _notes(owner_id) == [] and _notes(guest_id) == []
