"""가족 이름 변경: 가족 관리자(owner/admin)만 바꿀 수 있고 다른 가족에는 영향이 없다."""

from tests.helpers import signup  # noqa: F401  (헬퍼 모듈이 테스트 DB 를 준비한다)

from .test_join_approval import account, create_group, join

P = "/family-group"


def _member(client, group, login_id, name):
    """초대 코드로 들어와 승인된 일반 구성원의 (헤더, id) 를 돌려준다."""
    owner = group["_owner"]
    headers, user_id = account(client, login_id, name)
    request = join(client, headers, group["invite_code"]).json()
    if request["status"] != "approved":  # 가족의 자동 승인이 꺼져 있으면 관리자가 승인한다
        approved = client.post(f"{P}/groups/join-requests/{request['id']}/approve", headers=owner)
        assert approved.status_code == 200, approved.text
    return headers, user_id


def _family(client):
    owner, owner_id = account(client, "rename_owner", "엄마")
    group = create_group(client, owner, "우리 가족")
    group["_owner"] = owner
    return owner, owner_id, group


def rename(client, headers, name):
    return client.put(f"{P}/groups/me/name", json={"name": name}, headers=headers)


def test_owner_renames_and_everyone_sees_the_new_name(client):
    owner, _, group = _family(client)
    guest, _ = _member(client, group, "rename_guest", "지민")
    r = rename(client, owner, "  행복한 우리집  ")
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "행복한 우리집"  # 앞뒤 공백은 지운다
    assert client.get(f"{P}/groups/me", headers=owner).json()["name"] == "행복한 우리집"
    assert client.get(f"{P}/groups/me", headers=guest).json()["name"] == "행복한 우리집"


def test_admin_can_rename_but_plain_member_cannot(client):
    owner, _, group = _family(client)
    jimin, jimin_id = _member(client, group, "rename_jimin", "지민")
    sujin, _ = _member(client, group, "rename_sujin", "수진")
    promoted = client.put(
        f"{P}/groups/members/{jimin_id}/role", json={"role": "admin"}, headers=owner
    )
    assert promoted.status_code == 200, promoted.text

    assert rename(client, jimin, "지민이네").json()["name"] == "지민이네"  # admin 은 된다
    denied = rename(client, sujin, "수진이네")
    assert denied.status_code == 403 and denied.json()["code"] == "not_manager"
    assert client.get(f"{P}/groups/me", headers=owner).json()["name"] == "지민이네"


def test_name_must_be_1_to_60_chars_and_not_blank(client):
    owner, _, _ = _family(client)
    for bad in ("", "   ", "가" * 61):
        assert rename(client, owner, bad).status_code == 422, bad
    assert rename(client, owner, "가" * 60).status_code == 200
    assert client.get(f"{P}/groups/me", headers=owner).json()["name"] == "가" * 60


def test_user_without_a_group_gets_no_group_and_other_groups_are_untouched(client):
    owner, _, _ = _family(client)
    other, _ = account(client, "rename_other", "이웃")
    other_group = create_group(client, other, "이웃집")
    loner, _ = account(client, "rename_loner", "혼자")
    assert rename(client, loner, "아무개").json()["code"] == "no_group"

    assert rename(client, owner, "바뀐 이름").status_code == 200
    assert client.get(f"{P}/groups/me", headers=other).json()["name"] == other_group["name"]


def test_rename_requires_login(client):
    assert client.put(f"{P}/groups/me/name", json={"name": "x"}).status_code in (401, 403)
