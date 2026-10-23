"""가족 초대·가입 승인(PR 4-B): 초대 코드 → 참여 요청 → 관리자 승인/거절 → 구성원."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.features.family_group.models import GroupMember, Invite, InviteAttempt, JoinRequest
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.helpers import signup

P = "/family-group"
PASSWORD = "Sunny-day-2026"


def account(client, login_id, name=None):
    """정식 회원(아이디/비밀번호)을 만들고 Bearer 헤더와 id 를 돌려준다."""
    r = client.post(
        f"{P}/auth/signup",
        json={
            "login_id": login_id,
            "password": PASSWORD,
            "email": f"{login_id}@example.com",
            "name": name or login_id,
        },
    )
    assert r.status_code == 201, r.text
    token = client.post(
        f"{P}/auth/login", json={"login_id": login_id, "password": PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, r.json()["user"]["id"]


def create_group(client, headers, name="우리 가족"):
    r = client.post(f"{P}/groups", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def join(client, headers, code):
    return client.post(f"{P}/groups/join", json={"code": code}, headers=headers)


def members_of(group_id):
    with SessionLocal() as db:
        rows = db.scalars(select(GroupMember).where(GroupMember.group_id == group_id)).all()
        return {m.user_id: m.role for m in rows}


def new_code(client, headers):
    r = client.post(f"{P}/groups/invites/reissue", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["invite_code"]


# ---------- 전체 흐름 ----------
def test_invite_request_approve_flow(client):
    owner, owner_id = account(client, "owner_kim", "엄마")
    group = create_group(client, owner)
    assert (
        len(group["invite_code"]) == 10
        and group["my_role"] == "owner"
        and group["invite_expires_at"]
    )
    assert group["members"][0]["group_role"] == "owner"

    guest, guest_id = account(client, "guest_lee", "지민")
    pending = join(client, guest, group["invite_code"].lower())  # 소문자로 입력해도 된다
    assert pending.status_code == 200, pending.text
    body = pending.json()
    assert (
        body["status"] == "pending" and body["group_name"] == "우리 가족" and "members" not in body
    )
    assert guest_id not in members_of(group["id"])  # 승인 전에는 구성원이 아니다

    # 승인 전에는 가족 데이터에 접근할 수 없다
    assert client.get(f"{P}/groups/me", headers=guest).status_code == 404
    assert client.get("/family-chat/messages", headers=guest).json()["code"] == "no_group"
    mine = client.get(f"{P}/groups/join-requests/mine", headers=guest).json()
    assert mine["id"] == body["id"] and mine["status"] == "pending"

    listed = client.get(f"{P}/groups/me/join-requests", headers=owner).json()
    assert [(r["id"], r["user_name"], r["user_id"]) for r in listed] == [
        (body["id"], "지민", guest_id)
    ]

    approved = client.post(f"{P}/groups/join-requests/{body['id']}/approve", headers=owner)
    assert approved.status_code == 200, approved.text
    assert {m["name"]: m["group_role"] for m in approved.json()["members"]} == {
        "엄마": "owner",
        "지민": "member",
    }
    assert members_of(group["id"])[guest_id] == "member"
    assert client.get(f"{P}/groups/me", headers=guest).json()["id"] == group["id"]
    assert (
        client.get(f"{P}/groups/join-requests/mine", headers=guest).json()["status"] == "approved"
    )
    assert client.get(f"{P}/groups/me/join-requests", headers=owner).json() == []
    # 구성원에게는 초대 코드가 보이지 않고, 자기 권한만 보인다
    seen = client.get(f"{P}/groups/me", headers=guest).json()
    assert seen["invite_code"] is None and seen["my_role"] == "member"


def test_reject_does_not_refund_the_use_and_a_new_code_works(client):
    owner, _ = account(client, "owner_kim")
    group = create_group(client, owner)
    guest, guest_id = account(client, "guest_lee")
    req = join(client, guest, group["invite_code"]).json()
    assert (
        client.post(f"{P}/groups/join-requests/{req['id']}/reject", headers=owner).status_code
        == 204
    )
    assert (
        client.get(f"{P}/groups/join-requests/mine", headers=guest).json()["status"] == "rejected"
    )
    assert guest_id not in members_of(group["id"])
    assert client.get(f"{P}/groups/me", headers=guest).status_code == 404
    # 거절돼도 쓴 횟수는 돌려주지 않는다: 같은 코드는 다시 못 쓴다
    assert join(client, guest, group["invite_code"]).json()["code"] == "invalid_invite"
    again = join(client, guest, new_code(client, owner))  # 새 코드로는 다시 신청할 수 있다
    assert again.json()["status"] == "pending" and again.json()["id"] != req["id"]


# ---------- 초대 코드 ----------
def test_code_is_single_use_expires_and_can_be_revoked(client):
    owner, _ = account(client, "owner_kim")
    group = create_group(client, owner)
    a, _ = account(client, "guest_a")
    b, _ = account(client, "guest_b")
    assert join(client, a, group["invite_code"]).status_code == 200
    assert join(client, b, group["invite_code"]).json()["code"] == "invalid_invite"  # 1회 소진

    code = new_code(client, owner)
    assert (
        join(client, a, group["invite_code"]).json()["code"] == "invalid_invite"
    )  # 재발급하면 이전 코드는 폐기
    with SessionLocal() as db:
        db.query(Invite).filter_by(code=code).update(
            {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
        db.commit()
    assert join(client, b, code).json()["code"] == "invalid_invite"  # 만료
    assert (
        client.get(f"{P}/groups/me", headers=owner).json()["invite_code"] is None
    )  # 만료된 코드는 보여주지 않는다

    fresh = new_code(client, owner)
    assert client.post(f"{P}/groups/invites/revoke", headers=owner).status_code == 204
    assert join(client, b, fresh).json()["code"] == "invalid_invite"  # 폐기


def test_same_user_requesting_twice_reuses_the_pending_request(client, monkeypatch):
    monkeypatch.setattr(settings, "invite_max_uses", 3)
    owner, _ = account(client, "owner_kim")
    group = create_group(client, owner)
    guest, _ = account(client, "guest_lee")
    first = join(client, guest, group["invite_code"]).json()
    second = join(client, guest, group["invite_code"]).json()
    assert first["id"] == second["id"]
    with SessionLocal() as db:
        assert (
            db.query(Invite).filter_by(group_id=group["id"]).one().use_count == 1
        )  # 다시 쓰지 않았다
        assert db.query(JoinRequest).count() == 1


def test_member_cannot_join_the_group_they_are_already_in(client):
    owner, _ = account(client, "owner_kim")
    create_group(client, owner)
    code = new_code(client, owner)
    r = join(client, owner, code)
    assert r.status_code == 409 and r.json()["code"] == "already_member"


# ---------- 권한 ----------
def test_nobody_can_raise_their_own_role_through_request_values(client):
    owner, _ = account(client, "owner_kim")
    group = create_group(client, owner)
    guest, guest_id = account(client, "guest_lee")
    req = client.post(
        f"{P}/groups/join",
        json={"code": group["invite_code"], "role": "owner", "group_role": "admin"},
        headers=guest,
    )
    assert req.status_code == 200 and req.json()["status"] == "pending"
    ok = client.post(
        f"{P}/groups/join-requests/{req.json()['id']}/approve",
        json={"role": "owner"},
        headers=owner,
    )
    assert ok.status_code == 200
    assert members_of(group["id"])[guest_id] == "member"  # 승인돼도 항상 member
    # 구성원은 관리자 기능을 쓸 수 없다
    assert client.post(f"{P}/groups/invites/reissue", headers=guest).json()["code"] == "not_manager"
    assert client.post(f"{P}/groups/invites/revoke", headers=guest).status_code == 403
    assert client.get(f"{P}/groups/me/join-requests", headers=guest).json()["code"] == "not_manager"
    assert members_of(group["id"])[guest_id] == "member"


def test_only_managers_decide_and_other_groups_are_invisible(client):
    owner, _ = account(client, "owner_kim")
    group = create_group(client, owner)
    member, _ = account(client, "member_a")
    applicant, _ = account(client, "guest_lee")
    first = join(client, member, group["invite_code"]).json()
    client.post(f"{P}/groups/join-requests/{first['id']}/approve", headers=owner)
    req = join(client, applicant, new_code(client, owner)).json()

    rid = req["id"]
    for action in ("approve", "reject"):
        denied = client.post(f"{P}/groups/join-requests/{rid}/{action}", headers=member)
        assert denied.status_code == 403 and denied.json()["code"] == "not_manager"
    stranger, _ = account(client, "other_owner")
    create_group(client, stranger, "다른 가족")
    for action in ("approve", "reject"):  # 다른 그룹의 관리자는 요청이 있는지조차 알 수 없다
        assert (
            client.post(f"{P}/groups/join-requests/{rid}/{action}", headers=stranger).status_code
            == 404
        )
    assert client.get(f"{P}/groups/me/join-requests", headers=stranger).json() == []
    assert client.post(f"{P}/groups/join-requests/nope/approve", headers=owner).status_code == 404
    assert (
        client.post(f"{P}/groups/join-requests/{rid}/approve").status_code == 401
    )  # 로그인 없이는 안 된다
    with SessionLocal() as db:
        assert db.get(JoinRequest, rid).status == "pending"  # 위 시도는 아무것도 바꾸지 않았다


def test_cancel_by_the_applicant_only_and_decided_requests_stay_decided(client):
    owner, _ = account(client, "owner_kim")
    group = create_group(client, owner)
    guest, _ = account(client, "guest_lee")
    other, _ = account(client, "guest_two")
    req = join(client, guest, group["invite_code"]).json()
    assert (
        client.post(f"{P}/groups/join-requests/{req['id']}/cancel", headers=other).status_code
        == 404
    )
    assert (
        client.post(f"{P}/groups/join-requests/{req['id']}/cancel", headers=guest).status_code
        == 204
    )
    assert (
        client.get(f"{P}/groups/join-requests/mine", headers=guest).json()["status"] == "cancelled"
    )
    late = client.post(f"{P}/groups/join-requests/{req['id']}/approve", headers=owner)
    assert late.status_code == 409 and late.json()["code"] == "join_request_already_decided"
    assert (
        client.post(f"{P}/groups/join-requests/{req['id']}/cancel", headers=guest).status_code
        == 409
    )
    assert client.get(f"{P}/groups/me", headers=guest).status_code == 404


# ---------- 동시성 ----------
def test_simultaneous_approvals_only_one_wins(client):
    owner, _ = account(client, "owner_kim")
    group = create_group(client, owner)
    guest, guest_id = account(client, "guest_lee")
    req = join(client, guest, group["invite_code"]).json()

    def go(_):
        return client.post(
            f"{P}/groups/join-requests/{req['id']}/approve", headers=owner
        ).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = sorted(pool.map(go, range(6)))
    assert codes == [200] + [409] * 5, codes
    assert list(members_of(group["id"]).values()).count("member") == 1


def test_one_use_code_submitted_by_many_people_at_once_creates_one_request(client):
    owner, _ = account(client, "owner_kim")
    group = create_group(client, owner)
    guests = [account(client, f"guest_{i}")[0] for i in range(5)]

    def go(headers):
        return join(client, headers, group["invite_code"]).status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        codes = sorted(pool.map(go, guests))
    assert codes == [200] + [400] * 4, codes
    with SessionLocal() as db:
        assert db.query(JoinRequest).count() == 1
        assert db.query(Invite).filter_by(group_id=group["id"]).one().use_count == 1


# ---------- 시도 제한 ----------
def test_wrong_codes_lock_the_account_for_the_window_then_unlock(client):
    owner, _ = account(client, "owner_kim")
    group = create_group(client, owner)
    guest, guest_id = account(client, "guest_lee")
    for _ in range(settings.invite_max_failures):
        assert join(client, guest, "WRONGCODE1").json()["code"] == "invalid_invite"
    blocked = join(client, guest, group["invite_code"])  # 맞는 코드도 막힌다
    assert blocked.status_code == 429 and blocked.json()["code"] == "too_many_attempts"
    assert 1 <= int(blocked.headers["Retry-After"]) <= settings.invite_failure_window_seconds + 1
    with SessionLocal() as db:
        assert db.query(InviteAttempt).filter_by(user_id=guest_id, success=False).count() == 5
        assert (
            db.query(InviteAttempt).filter(InviteAttempt.invite_id.is_not(None)).count() == 0
        )  # 코드는 저장하지 않는다
        db.query(InviteAttempt).update({"created_at": datetime.now(UTC) - timedelta(minutes=16)})
        db.commit()
    assert (
        join(client, guest, group["invite_code"]).json()["status"] == "pending"
    )  # 15분이 지나면 다시 시도할 수 있다
    with SessionLocal() as db:
        assert db.query(InviteAttempt).filter_by(success=True).one().invite_id is not None


# ---------- 기존 익명 계정 호환 ----------
def test_anonymous_accounts_keep_the_old_behavior(client):
    a = signup(client, "지민")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=a).json()
    assert len(group["invite_code"]) == 8  # 기존 방식 코드: 제한 없음
    b, c = signup(client, "수진"), signup(client, "엄마")
    for headers in (b, c):  # 같은 코드로 여러 명, 승인 없이 바로
        joined = client.post(
            f"{P}/groups/join", json={"code": group["invite_code"]}, headers=headers
        )
        assert joined.status_code == 200 and "members" in joined.json()
    assert len(members_of(group["id"])) == 3


def test_new_policy_codes_need_approval_even_for_anonymous_accounts(client):
    owner, _ = account(client, "owner_kim")
    group = create_group(client, owner)
    anon = signup(client, "손님")
    r = client.post(f"{P}/groups/join", json={"code": group["invite_code"]}, headers=anon)
    assert r.status_code == 200 and r.json()["status"] == "pending"  # 우회로가 없다
    assert client.get(f"{P}/groups/me", headers=anon).status_code == 404


def test_formal_member_joining_an_anonymous_group_needs_the_owners_approval(client):
    a = signup(client, "지민")
    group = client.post(f"{P}/groups", json={"name": "우리 가족"}, headers=a).json()
    guest, guest_id = account(client, "guest_lee")
    req = join(client, guest, group["invite_code"]).json()
    assert req["status"] == "pending" and guest_id not in members_of(group["id"])
    assert (
        client.post(f"{P}/groups/join-requests/{req['id']}/approve", headers=a).status_code == 200
    )
    assert members_of(group["id"])[guest_id] == "member"


def test_groups_stay_isolated_after_approval(client):
    owner_a, _ = account(client, "owner_a")
    owner_b, _ = account(client, "owner_b")
    group_a, group_b = (
        create_group(client, owner_a, "A 가족"),
        create_group(client, owner_b, "B 가족"),
    )
    guest, _ = account(client, "guest_lee")
    req = join(client, guest, group_a["invite_code"]).json()
    client.post(f"{P}/groups/join-requests/{req['id']}/approve", headers=owner_a)
    me = client.get(f"{P}/groups/me", headers=guest).json()
    assert me["id"] == group_a["id"] and me["id"] != group_b["id"]
    assert client.get(f"{P}/groups/me/join-requests", headers=guest).json()["code"] == "not_manager"
