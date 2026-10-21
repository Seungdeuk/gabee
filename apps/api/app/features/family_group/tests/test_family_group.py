"""가입, 가족 그룹, 초대 코드, 토큰 검사."""

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
    joined = client.post(
        "/family-group/groups/join", json={"code": g["invite_code"].lower()}, headers=b
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
    for path in ("/family-chat/messages", "/schedule/events", "/billing/expenses", "/care/records"):
        r = client.get(path, headers=a)
        assert r.status_code == 400 and r.json()["code"] == "no_group", path
