"""가입, 가족 그룹, 초대 코드, 토큰 검사."""

from app.features.family_group.models import GroupMember, Invite
from app.shared.db import SessionLocal
from tests.helpers import signup


def test_signup_group_invite_and_join(client):
    a = signup(client, "지민")
    assert client.get("/family-group/groups/me", headers=a).status_code == 404  # 아직 그룹 없음
    g = client.post("/family-group/groups", json={"name": "우리 가족"}, headers=a).json()
    assert len(g["invite_code"]) == 8 and [m["name"] for m in g["members"]] == ["지민"]

    b = signup(client, "수진", "parent")
    assert (
        client.post("/family-group/groups/join", json={"code": "WRONGCODE"}, headers=b).json()[
            "code"
        ]
        == "invalid_invite"
    )
    pending = client.post(
        "/family-group/groups/join", json={"code": g["invite_code"].lower()}, headers=b
    ).json()
    assert pending["status"] == "pending" and pending["group_id"] == g["id"]
    assert (
        client.get("/family-group/groups/me", headers=b).status_code == 404
    )  # 승인 전에는 구성원이 아니다
    joined = client.post(
        f"/family-group/groups/join-requests/{pending['id']}/approve", headers=a
    ).json()
    assert {m["name"] for m in joined["members"]} == {"지민", "수진"}
    assert client.get("/family-group/me", headers=b).json()["active_group_id"] == g["id"]


def test_token_is_required_and_errors_have_code_and_message(client):
    r = client.get("/family-group/me")
    assert (
        r.status_code == 401
        and set(r.json()) == {"code", "message"}
        and r.json()["code"] == "token_required"
    )
    assert (
        client.get("/family-group/me", headers={"X-Gyeot-Token": "nope"}).json()["code"]
        == "token_invalid"
    )
    assert client.post("/family-group/users", json={"name": "", "role": "child"}).status_code == 422


def test_group_features_need_a_group(client):
    a = signup(client)
    for path in ("/family-chat/messages", "/schedule/events", "/billing/expenses"):
        r = client.get(path, headers=a)
        assert r.status_code == 400 and r.json()["code"] == "no_group", path


def test_create_group_assigns_invite_id_and_owner_role(client):
    """PR 4-A 회귀 테스트: invites.id 가 비어 있어도(기존 호출부 그대로) INSERT 가 성공하고
    (ORM default=_uid), 그룹 생성자는 group_members.role='owner' 로 저장돼야 한다
    (repository.add_group() 이 명시적으로 role="owner" 를 넘기는지)."""
    a = signup(client, "지민")
    me = client.get("/family-group/me", headers=a).json()
    g = client.post("/family-group/groups", json={"name": "우리 가족"}, headers=a).json()
    assert g["invite_code"] and len(g["invite_code"]) >= 8

    db = SessionLocal()
    try:
        invite = db.query(Invite).filter_by(group_id=g["id"]).one()
        assert invite.id is not None and len(invite.id) > 0

        membership = db.get(GroupMember, (g["id"], me["id"]))
        assert membership is not None
        assert membership.role == "owner"
    finally:
        db.close()
