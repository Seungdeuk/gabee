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
