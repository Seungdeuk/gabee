"""가족 나가기(POST /family-group/groups/me/leave): 구성원·관리자는 나갈 수 있고, 소유자는 다른 구성원이 있으면 못 나간다."""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import or_, select

from app.features.family_group.models import GroupMember, MemberNickname, User
from app.shared.db import SessionLocal

from .test_join_approval import P, account, create_group, join, new_code

LEAVE = f"{P}/groups/me/leave"


def _enter(client, owner, headers):
    """초대 코드로 들어가 구성원이 된다(자동 승인이면 바로, 아니면 승인까지)."""
    r = join(client, headers, new_code(client, owner))
    assert r.status_code == 200, r.text
    if r.json()["status"] == "pending":
        ok = client.post(f"{P}/groups/join-requests/{r.json()['id']}/approve", headers=owner)
        assert ok.status_code == 200, ok.text


def family(client):
    owner, owner_id = account(client, "mom_kim", "엄마")
    group = create_group(client, owner)
    jimin, jimin_id = account(client, "jimin_lee", "지민")
    uncle, uncle_id = account(client, "uncle_park", "삼촌")
    _enter(client, owner, jimin)
    _enter(client, owner, uncle)
    return owner, owner_id, (jimin, jimin_id), (uncle, uncle_id), group


def roles(group_id):
    with SessionLocal() as db:
        rows = db.scalars(select(GroupMember).where(GroupMember.group_id == group_id)).all()
        return {m.user_id: m.role for m in rows}


def nick(client, headers, target_id, text):
    r = client.put(f"{P}/groups/me/nicknames/{target_id}", json={"nickname": text}, headers=headers)
    assert r.status_code == 200, r.text


def test_member_leaves(client):
    owner, owner_id, (jimin, jimin_id), (uncle, uncle_id), group = family(client)
    # 별명: 지민이 쓴 것, 지민에게 붙은 것, 무관한 것(엄마->삼촌)
    nick(client, jimin, uncle_id, "삼촌님")
    nick(client, uncle, jimin_id, "조카")
    nick(client, owner, uncle_id, "동생")
    assert len(client.get(f"{P}/groups/me", headers=owner).json()["members"]) == 3

    r = client.post(LEAVE, headers=jimin)
    assert r.status_code == 204 and r.content == b""

    # 나간 사람은 그룹 API 가 막힌다
    assert client.get(f"{P}/groups/me/nicknames", headers=jimin).json()["code"] == "no_group"
    assert client.get("/family-chat/messages", headers=jimin).json()["code"] == "no_group"
    with SessionLocal() as db:
        assert db.get(User, jimin_id).active_group_id is None
        gone = db.scalars(
            select(MemberNickname).where(
                or_(
                    MemberNickname.owner_user_id == jimin_id,
                    MemberNickname.target_user_id == jimin_id,
                )
            )
        ).all()
        assert gone == []
        # 남은 사람의 무관한 별명은 그대로
        assert db.get(MemberNickname, (group["id"], owner_id, uncle_id)).nickname == "동생"
    # 다른 구성원의 멤버십은 그대로, 가족은 N-1명
    assert roles(group["id"]) == {owner_id: "owner", uncle_id: "member"}
    seen = client.get(f"{P}/groups/me", headers=owner).json()
    assert len(seen["members"]) == 2
    assert client.get(f"{P}/groups/me", headers=uncle).status_code == 200


def test_admin_leaves(client):
    owner, owner_id, (jimin, jimin_id), _, group = family(client)
    r = client.put(f"{P}/groups/members/{jimin_id}/role", json={"role": "admin"}, headers=owner)
    assert r.status_code == 200, r.text
    assert client.post(LEAVE, headers=jimin).status_code == 204
    assert jimin_id not in roles(group["id"])


def test_owner_cannot_leave_while_others_are_members(client):
    owner, owner_id, _, _, group = family(client)
    r = client.post(LEAVE, headers=owner)
    assert r.status_code == 400 and r.json()["code"] == "cannot_leave_owner"
    assert roles(group["id"])[owner_id] == "owner"
    assert client.get(f"{P}/groups/me", headers=owner).status_code == 200

    # 혼자인 소유자는 나갈 수 있다(가족 데이터가 모두 지워진다: test_leave_empty_group.py)


def test_user_without_group_gets_no_group(client):
    headers, _ = account(client, "lone_kim", "무소속")
    r = client.post(LEAVE, headers=headers)
    assert r.status_code == 400 and r.json()["code"] == "no_group"


def test_leave_requires_auth(client):
    assert client.post(LEAVE).status_code == 401


def test_left_user_can_request_to_join_again(client):
    owner, owner_id, (jimin, jimin_id), _, group = family(client)
    assert client.post(LEAVE, headers=jimin).status_code == 204
    r = join(client, jimin, new_code(client, owner))
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("pending", "approved")
    if r.json()["status"] == "pending":
        ok = client.post(f"{P}/groups/join-requests/{r.json()['id']}/approve", headers=owner)
        assert ok.status_code == 200, ok.text
    assert roles(group["id"])[jimin_id] == "member"


def test_second_leave_is_not_a_server_error(client):
    _, _, (jimin, _), _, _ = family(client)
    assert client.post(LEAVE, headers=jimin).status_code == 204
    r = client.post(LEAVE, headers=jimin)
    assert r.status_code in (400, 403) and r.json()["code"] in ("no_group", "not_member")


def test_concurrent_leave_never_500(client):
    _, _, (jimin, jimin_id), _, group = family(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda _: client.post(LEAVE, headers=jimin).status_code, range(2)))
    assert 204 in codes and all(c in (204, 400, 403) for c in codes), codes
    assert jimin_id not in roles(group["id"])


def test_leave_active_group_switches_to_most_recent_remaining(client):
    owner_a, _ = account(client, "mom_a", "엄마A")
    group_a = create_group(client, owner_a, "A 가족")
    owner_b, _ = account(client, "mom_b", "엄마B")
    group_b = create_group(client, owner_b, "B 가족")
    kid, kid_id = account(client, "kid_lee", "아이")
    _enter(client, owner_a, kid)
    _enter(client, owner_b, kid)  # 마지막에 들어간 B 가 활성 그룹
    with SessionLocal() as db:
        assert db.get(User, kid_id).active_group_id == group_b["id"]

    assert client.post(LEAVE, headers=kid).status_code == 204

    with SessionLocal() as db:
        assert db.get(User, kid_id).active_group_id == group_a["id"]
    seen = client.get(f"{P}/groups/me", headers=kid)
    assert seen.status_code == 200 and seen.json()["id"] == group_a["id"]


def test_leave_retries_once_on_integrity_error(client, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.features.family_group import profile_repository as prepo

    _, _, (jimin, jimin_id), _, group = family(client)
    real = prepo.delete_member_if_not_owner
    calls = {"n": 0}

    def flaky(db, group_id, user_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("DELETE", {}, Exception("fk"))
        return real(db, group_id, user_id)

    monkeypatch.setattr(prepo, "delete_member_if_not_owner", flaky)
    assert client.post(LEAVE, headers=jimin).status_code == 204
    assert calls["n"] == 2
    assert jimin_id not in roles(group["id"])
