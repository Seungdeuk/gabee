"""운영 관리자 API(/admin)의 안쪽 문: Bearer 정식 회원 + users.is_staff 만 통과한다."""

from sqlalchemy import update

from app.features.family_group.models import GroupMember, User
from app.shared.db import SessionLocal
from tests.helpers import signup

ME = "/admin/me"
PASSWORD = "Sunny-day-2026"


def _login(client, login_id="jimin_kim") -> tuple[dict, str]:
    body = {
        "login_id": login_id,
        "password": PASSWORD,
        "email": f"{login_id}@example.com",
        "name": "김지민",
    }
    assert client.post("/family-group/auth/signup", json=body).status_code == 201
    r = client.post("/family-group/auth/login", json={"login_id": login_id, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["user"]["id"]


def _make_staff(user_id: str) -> None:
    with SessionLocal() as db:
        db.execute(update(User).where(User.id == user_id).values(is_staff=True))
        db.commit()


def test_requires_login(client):
    assert client.get(ME).status_code == 401


def test_new_member_is_not_staff(client):
    headers, _ = _login(client)
    r = client.get(ME, headers=headers)
    assert r.status_code == 404  # 관리자가 아니면 경로가 있다는 것도 알리지 않는다


def test_staff_member_passes(client):
    headers, user_id = _login(client)
    _make_staff(user_id)
    r = client.get(ME, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"id": user_id, "name": "김지민", "login_id": "jimin_kim"}


def test_family_owner_role_is_not_staff(client):
    headers, user_id = _login(client)
    client.post("/family-group/groups", json={"name": "우리 가족"}, headers=headers)
    with SessionLocal() as db:
        assert db.get(GroupMember, (db.get(User, user_id).active_group_id, user_id)).role == "owner"
    assert client.get(ME, headers=headers).status_code == 404


LISTS = ("/admin/members", "/admin/groups", "/admin/features", "/admin/testers")


def test_lists_are_staff_only(client):
    for path in LISTS:
        assert client.get(path).status_code == 401, path
    headers, _ = _login(client)
    for path in LISTS:
        assert client.get(path, headers=headers).status_code == 404, path


def test_lists_count_members_and_groups(client):
    headers, user_id = _login(client)
    _make_staff(user_id)
    r = client.post("/family-group/groups", json={"name": "우리 가족"}, headers=headers)
    assert r.status_code in (200, 201), r.text

    members = client.get("/admin/members", headers=headers).json()
    assert members["total"] >= 1 and members["joined_this_week"] >= 1
    me = next(r for r in members["rows"] if r["id"] == user_id)
    assert me["has_family"] is True and me["last_login_at"] is not None
    assert "email" not in me  # 이메일은 돌려주지 않는다

    groups = client.get("/admin/groups", headers=headers).json()
    assert groups["total"] == 1
    assert groups["rows"][0]["name"] == "우리 가족" and groups["rows"][0]["members"] == 1
    assert groups["sizes"] == [{"members": 1, "groups": 1}]

    features = client.get("/admin/features", headers=headers).json()
    assert [r["key"] for r in features["rows"]] == ["schedule", "chat", "care", "billing"]
    assert features["families_total"] == 1

    assert client.get("/admin/testers", headers=headers).status_code == 200


def test_legacy_token_cannot_reach_admin_even_if_staff(client):
    headers = signup(client, "익명")
    user_id = client.get("/family-group/me", headers=headers).json()["id"]
    _make_staff(user_id)
    assert client.get(ME, headers=headers).status_code == 401
