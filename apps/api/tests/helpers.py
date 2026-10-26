def signup(client, name="지민", role="child") -> dict:
    """가입하고 이후 요청에 쓸 헤더를 돌려준다."""
    r = client.post("/family-group/users", json={"name": name, "role": role})
    assert r.status_code == 201, r.text
    return {"X-Gyeot-Token": r.json()["token"]}


def promote_admin(client, owner_headers, name) -> None:
    """소유자가 같은 가족의 구성원(name)을 관리자(admin)로 지정한다. 용돈 지급·취소 같은 관리 권한은 이쪽이다."""
    members = client.get("/family-group/groups/me", headers=owner_headers).json()["members"]
    target = next(m["id"] for m in members if m["name"] == name)
    r = client.put(
        f"/family-group/groups/members/{target}/role",
        json={"role": "admin"},
        headers=owner_headers,
    )
    assert r.status_code == 200, r.text
