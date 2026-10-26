"""가족 관계·표시 이름·별명·관리자 지정(PR 4-C)."""

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.features.family_group.models import GroupMember, MemberNickname
from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

from .test_join_approval import P, account, create_group, join


def family(client):
    """소유자(엄마)와 구성원(지민), 구성원(삼촌)이 있는 가족. 정식 회원, 승인까지 끝난 상태."""
    owner, owner_id = account(client, "mom_kim", "엄마")
    group = create_group(client, owner)
    people = {}
    for login_id, name in (("jimin_lee", "지민"), ("uncle_park", "삼촌")):
        headers, user_id = account(client, login_id, name)
        req = join(client, headers, _fresh_code(client, owner)).json()
        assert (
            client.post(f"{P}/groups/join-requests/{req['id']}/approve", headers=owner).status_code
            == 200
        )
        people[name] = (headers, user_id)
    return owner, owner_id, people["지민"], people["삼촌"], group


def _fresh_code(client, owner):
    return client.post(f"{P}/groups/invites/reissue", headers=owner).json()["invite_code"]


def member(group_json, user_id):
    return next(m for m in group_json["members"] if m["id"] == user_id)


def put(client, headers, path, body):
    return client.put(f"{P}{path}", json=body, headers=headers)


def db_member(group_id, user_id) -> GroupMember:
    with SessionLocal() as db:
        return db.get(GroupMember, (group_id, user_id))


# ---------- 가족 관계 · 표시 이름 ----------
def test_member_sets_own_name_and_relation(client):
    owner, owner_id, (jimin, jimin_id), _, group = family(client)
    r = put(
        client,
        jimin,
        "/groups/me/profile",
        {"display_name": "  우리   지민 ", "family_relation": "daughter"},
    )
    assert r.status_code == 200, r.text
    me = member(r.json(), jimin_id)
    assert r.json()["my_id"] == jimin_id  # 구성원 목록에서 나를 찾을 수 있다
    assert (me["display_name"], me["family_relation"], me["name"]) == (
        "우리 지민",
        "daughter",
        "지민",
    )
    # 다른 구성원에게도 그대로 보이고, 다른 사람의 프로필은 바뀌지 않는다
    seen = client.get(f"{P}/groups/me", headers=owner).json()
    assert member(seen, jimin_id)["family_relation"] == "daughter"
    assert (
        member(seen, owner_id)["display_name"] is None
        and member(seen, owner_id)["family_relation"] is None
    )


def test_profile_updates_only_the_sent_fields_and_null_clears(client):
    _, _, (jimin, jimin_id), _, group = family(client)
    put(client, jimin, "/groups/me/profile", {"display_name": "지민이", "family_relation": "son"})
    r = put(
        client, jimin, "/groups/me/profile", {"family_relation": "daughter"}
    )  # 이름은 보내지 않아 그대로
    me = member(r.json(), jimin_id)
    assert (me["display_name"], me["family_relation"]) == ("지민이", "daughter")
    cleared = put(
        client, jimin, "/groups/me/profile", {"display_name": None, "family_relation": None}
    )
    me = member(cleared.json(), jimin_id)
    assert me["display_name"] is None and me["family_relation"] is None
    assert put(client, jimin, "/groups/me/profile", {"display_name": "   "}).json()[
        "members"
    ]  # 공백만 있으면 지운다


def test_other_relation_keeps_a_typed_detail_and_other_relations_drop_it(client):
    _, _, (jimin, jimin_id), _, group = family(client)
    r = put(
        client,
        jimin,
        "/groups/me/profile",
        {"family_relation": "other", "family_relation_detail": " 이모 "},
    )
    me = member(r.json(), jimin_id)
    assert (me["family_relation"], me["family_relation_detail"]) == ("other", "이모")
    again = put(
        client, jimin, "/groups/me/profile", {"family_relation_detail": "고모"}
    )  # 관계는 그대로 other
    assert member(again.json(), jimin_id)["family_relation_detail"] == "고모"
    changed = put(client, jimin, "/groups/me/profile", {"family_relation": "mom"})
    me = member(changed.json(), jimin_id)
    assert (me["family_relation"], me["family_relation_detail"]) == (
        "mom",
        None,
    )  # 직접 입력은 남기지 않는다
    bad = put(client, jimin, "/groups/me/profile", {"family_relation_detail": "이모"})
    assert bad.status_code == 400 and bad.json()["code"] == "relation_detail_needs_other"


def test_profile_validation(client):
    _, _, (jimin, _), _, _ = family(client)
    assert (
        put(client, jimin, "/groups/me/profile", {"family_relation": "cousin"}).status_code == 422
    )
    too_long = put(client, jimin, "/groups/me/profile", {"display_name": "가" * 41})
    assert too_long.status_code == 400 and too_long.json()["code"] == "invalid_display_name"
    put(client, jimin, "/groups/me/profile", {"family_relation": "other"})
    long_detail = put(client, jimin, "/groups/me/profile", {"family_relation_detail": "가" * 41})
    assert (
        long_detail.status_code == 400 and long_detail.json()["code"] == "invalid_relation_detail"
    )


def test_profile_only_touches_my_membership_and_needs_a_group(client):
    owner, owner_id, (jimin, jimin_id), (uncle, uncle_id), group = family(client)
    put(
        client, jimin, "/groups/me/profile", {"display_name": "지민", "family_relation": "daughter"}
    )
    assert db_member(group["id"], uncle_id).family_relation is None
    assert db_member(group["id"], owner_id).display_name is None
    loner, _ = account(client, "loner_a", "혼자")
    nogroup = put(client, loner, "/groups/me/profile", {"display_name": "x"})
    assert nogroup.status_code == 400 and nogroup.json()["code"] == "no_group"
    assert client.put(f"{P}/groups/me/profile", json={}).status_code == 401


# ---------- 관리자 지정 ----------
def test_only_the_owner_appoints_and_dismisses_admins(client):
    owner, owner_id, (jimin, jimin_id), (uncle, uncle_id), group = family(client)
    r = put(client, owner, f"/groups/members/{jimin_id}/role", {"role": "admin"})
    assert r.status_code == 200, r.text
    assert member(r.json(), jimin_id)["group_role"] == "admin"
    assert db_member(group["id"], jimin_id).role == "admin"
    # 관리자가 되면 초대·승인을 할 수 있다(4-B 권한과 이어진다)
    assert client.post(f"{P}/groups/invites/reissue", headers=jimin).status_code == 200
    seen = client.get(f"{P}/groups/me", headers=jimin).json()
    assert seen["my_role"] == "admin" and seen["invite_code"]
    # 관리자끼리·구성원은 지정할 수 없다
    for headers in (jimin, uncle):
        denied = put(client, headers, f"/groups/members/{uncle_id}/role", {"role": "admin"})
        assert denied.status_code == 403 and denied.json()["code"] == "not_owner"
    # 해제
    back = put(client, owner, f"/groups/members/{jimin_id}/role", {"role": "member"})
    assert member(back.json(), jimin_id)["group_role"] == "member"
    assert client.post(f"{P}/groups/invites/reissue", headers=jimin).status_code == 403


def test_owner_role_cannot_be_changed_or_granted(client):
    owner, owner_id, (jimin, jimin_id), _, group = family(client)
    self_change = put(client, owner, f"/groups/members/{owner_id}/role", {"role": "member"})
    assert self_change.status_code == 400 and self_change.json()["code"] == "cannot_change_owner"
    for role in ("owner", "root", ""):
        assert (
            put(client, owner, f"/groups/members/{jimin_id}/role", {"role": role}).status_code
            == 422
        )
    assert put(
        client, jimin, f"/groups/members/{jimin_id}/role", {"role": "owner"}
    ).status_code in (403, 422)
    with SessionLocal() as db:
        roles = [
            m.role
            for m in db.scalars(select(GroupMember).where(GroupMember.group_id == group["id"]))
        ]
    assert roles.count("owner") == 1 and db_member(group["id"], owner_id).role == "owner"


def test_role_change_does_not_reach_other_groups_or_unknown_people(client):
    owner, _, (jimin, jimin_id), _, group = family(client)
    other_owner, other_owner_id = account(client, "other_owner", "남")
    other_group = create_group(client, other_owner, "다른 가족")
    stranger = put(client, owner, f"/groups/members/{other_owner_id}/role", {"role": "admin"})
    assert stranger.status_code == 404  # 다른 그룹 사람은 대상이 될 수 없다
    assert put(client, owner, "/groups/members/nobody/role", {"role": "admin"}).status_code == 404
    assert (
        put(client, other_owner, f"/groups/members/{jimin_id}/role", {"role": "admin"}).status_code
        == 404
    )
    assert db_member(group["id"], jimin_id).role == "member"
    assert other_group["id"] != group["id"]


def test_simultaneous_role_changes_never_leave_two_owners(client):
    owner, owner_id, (jimin, jimin_id), _, group = family(client)

    def go(i):
        role = "admin" if i % 2 == 0 else "member"
        return put(client, owner, f"/groups/members/{jimin_id}/role", {"role": role}).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert set(pool.map(go, range(6))) == {200}
    with SessionLocal() as db:
        roles = [
            m.role
            for m in db.scalars(select(GroupMember).where(GroupMember.group_id == group["id"]))
        ]
    assert roles.count("owner") == 1 and db_member(group["id"], jimin_id).role in (
        "admin",
        "member",
    )


# ---------- 개인별 별명 ----------
def test_nicknames_are_private_to_their_author(client):
    owner, owner_id, (jimin, jimin_id), (uncle, uncle_id), group = family(client)
    r = put(
        client,
        jimin,
        f"/groups/me/nicknames/{uncle_id}",
        {"nickname": " 멋진  삼촌 ", "memo": "생일 3월"},
    )
    assert r.status_code == 200 and r.json() == {
        "target_user_id": uncle_id,
        "nickname": "멋진 삼촌",
        "memo": "생일 3월",
    }
    mine = client.get(f"{P}/groups/me/nicknames", headers=jimin).json()
    assert mine == [{"target_user_id": uncle_id, "nickname": "멋진 삼촌", "memo": "생일 3월"}]
    # 삼촌 본인과 다른 구성원에게는 보이지 않는다
    assert client.get(f"{P}/groups/me/nicknames", headers=uncle).json() == []
    assert client.get(f"{P}/groups/me/nicknames", headers=owner).json() == []
    # 가족 전체 프로필에도 영향이 없다
    shown = member(client.get(f"{P}/groups/me", headers=owner).json(), uncle_id)
    assert shown["name"] == "삼촌" and shown["display_name"] is None and "멋진" not in str(shown)
    # 다른 사람이 같은 대상에 쓴 별명은 따로 저장된다
    put(client, owner, f"/groups/me/nicknames/{uncle_id}", {"nickname": "삼촌님"})
    assert (
        client.get(f"{P}/groups/me/nicknames", headers=jimin).json()[0]["nickname"] == "멋진 삼촌"
    )
    with SessionLocal() as db:
        assert db.query(MemberNickname).count() == 2


def test_nickname_update_clear_and_validation(client):
    _, _, (jimin, jimin_id), (uncle, uncle_id), _ = family(client)
    path = f"/groups/me/nicknames/{uncle_id}"
    put(client, jimin, path, {"nickname": "삼촌"})
    updated = put(
        client, jimin, path, {"memo": "메모만"}
    )  # 보내지 않은 별명은 비워진다(같은 행을 덮어쓴다)
    assert updated.json()["nickname"] is None and updated.json()["memo"] == "메모만"
    cleared = put(client, jimin, path, {"nickname": "  ", "memo": ""})
    assert cleared.status_code == 200 and cleared.json()["nickname"] is None
    assert client.get(f"{P}/groups/me/nicknames", headers=jimin).json() == []  # 둘 다 비우면 지운다
    long = put(client, jimin, path, {"nickname": "가" * 41})
    assert long.status_code == 400 and long.json()["code"] == "invalid_nickname"
    me = put(client, jimin, f"/groups/me/nicknames/{jimin_id}", {"nickname": "나"})
    assert me.status_code == 400 and me.json()["code"] == "cannot_nickname_self"


def test_nickname_target_must_be_in_my_group(client):
    owner, _, (jimin, jimin_id), _, group = family(client)
    other_owner, other_owner_id = account(client, "other_owner", "남")
    create_group(client, other_owner, "다른 가족")
    assert (
        put(client, jimin, f"/groups/me/nicknames/{other_owner_id}", {"nickname": "남"}).status_code
        == 404
    )
    assert put(client, jimin, "/groups/me/nicknames/nobody", {"nickname": "x"}).status_code == 404
    with SessionLocal() as db:
        assert db.query(MemberNickname).count() == 0
    assert client.get(f"{P}/groups/me/nicknames", headers=other_owner).json() == []


# ---------- 기존 익명 계정 ----------
def test_anonymous_accounts_can_use_profile_and_nicknames(client):
    a, b = signup(client, "지민"), signup(client, "수진")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=a).json()
    join_family(client, a, group["invite_code"], b)
    me = client.get("/family-group/me", headers=b).json()
    r = put(client, b, "/groups/me/profile", {"display_name": "수진이", "family_relation": "mom"})
    assert member(r.json(), me["id"])["family_relation"] == "mom"
    owner_id = next(m["id"] for m in group["members"])
    assert put(client, b, f"/groups/me/nicknames/{owner_id}", {"nickname": "형"}).status_code == 200
    # 익명 소유자도 관리자를 지정할 수 있다(그룹 생성자는 owner)
    assert put(client, a, f"/groups/members/{me['id']}/role", {"role": "admin"}).status_code == 200
