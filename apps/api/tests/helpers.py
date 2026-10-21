def signup(client, name="지민", role="child") -> dict:
    """가입하고 이후 요청에 쓸 헤더를 돌려준다."""
    r = client.post("/family-group/users", json={"name": name, "role": role})
    assert r.status_code == 201, r.text
    return {"X-Gyeot-Token": r.json()["token"]}
