def signup(client, name="지민", role="child") -> dict:
    """가입하고 이후 요청에 쓸 헤더를 돌려준다."""
    r = client.post("/family-group/users", json={"name": name, "role": role})
    assert r.status_code == 201, r.text
    return {"X-Gyeot-Token": r.json()["token"]}


def allow_ai(client, headers, monkeypatch) -> None:
    """가족 AI 동의를 켜고(소유자·관리자 헤더) 시험에서는 사용자 쿨다운을 없앤다."""
    from app.shared.config import settings

    monkeypatch.setattr(settings, "ai_request_cooldown_seconds", 0)
    r = client.put("/family-chat/ai/settings", json={"enabled": True}, headers=headers)
    assert r.status_code == 200, r.text


def join_family(client, owner: dict, code: str, joiner: dict):
    """초대 코드로 가입을 신청하고 가족 관리자(owner)가 승인한다. 승인 응답(GroupOut)을 돌려준다.
    익명 계정도 정식 계정처럼 승인 대기를 거치므로, 구성원이 필요한 시험은 이 함수로 만든다."""
    r = client.post("/family-group/groups/join", json={"code": code}, headers=joiner)
    assert r.status_code == 200 and r.json()["status"] == "pending", r.text
    approved = client.post(
        f"/family-group/groups/join-requests/{r.json()['id']}/approve", headers=owner
    )
    assert approved.status_code == 200, approved.text
    return approved
