"""가족 그룹 멤버십 검증 — 인증만으로는 부족하고, group_members 기준 실제 소속이어야 한다.

current_group_id() 가 active_group_id 존재만 확인하던 시절의 회귀 테스트:
GroupMember 는 지우고 active_group_id 는 남겨둔("탈퇴했지만 캐시값이 안 지워진" 상태와
동등함) 사용자가 5개 도메인 어디서도 데이터를 보거나 쓸 수 없어야 한다.
"""

from app.features.family_group.models import GroupMember
from app.shared.db import SessionLocal


def _drop_membership(group_id: str, user_id: str) -> None:
    db = SessionLocal()
    member = db.get(GroupMember, (group_id, user_id))
    if member is not None:
        db.delete(member)
        db.commit()
    db.close()


GROUP_ENDPOINTS = (
    ("get", "/family-chat/messages", None),
    ("post", "/family-chat/messages", {"text": "몰래"}),
    ("get", "/family-chat/unread", None),
    ("get", "/family-chat/read-states", None),
    ("post", "/family-chat/read", {"message_id": 1}),
    ("get", "/family-chat/rooms", None),
    ("get", "/family-chat/media", None),
    ("get", "/family-chat/search?q=%EB%AA%B0%EB%9E%98", None),
    ("get", "/family-chat/todos", None),
    ("get", "/family-chat/pins", None),
    ("post", "/family-chat/pins", {"message_id": 1}),
    ("delete", "/family-chat/pins/1", None),
    ("get", "/family-chat/links", None),
    (
        "post",
        "/family-chat/links",
        {"message_id": 1, "kind": "todo", "target_id": "x", "title": "몰래"},
    ),
    ("delete", "/family-chat/links/x", None),
    ("post", "/family-chat/ai/preview", {}),
    ("post", "/family-chat/todos", {"title": "몰래"}),
    ("get", "/schedule/events", None),
    ("post", "/schedule/events", {"title": "몰래", "starts_at": "2026-12-01T00:00:00Z"}),
    ("get", "/billing/expenses", None),
    ("get", "/billing/summary", None),
    ("get", "/care/records", None),
    ("get", "/care/summary/today", None),
    ("get", "/ai-assistant/photos", None),
    ("post", "/ai-assistant/chat", {"message": "몰래"}),
    ("post", "/ai-assistant/knowledge/ask", {"question": "몰래"}),
)


def test_unauthenticated_requests_blocked_across_domains(client):
    for method, path, body in GROUP_ENDPOINTS:
        r = (
            getattr(client, method)(path, json=body)
            if body is not None
            else getattr(client, method)(path)
        )
        assert r.status_code == 401 and r.json()["code"] == "token_required", path


def test_non_member_blocked_even_with_stale_active_group_id(client, family):
    """b 는 그룹에 가입돼 있었지만(active_group_id 가 남아있음) GroupMember 를 지워
    '탈퇴와 동등한 상태'를 흉내낸다. 그래도 active_group_id 가 있으니 예전 코드라면
    통과했을 상황 — 지금은 403 not_member 로 막혀야 한다."""
    a, b, group = family
    b_id = client.get("/family-group/me", headers=b).json()["id"]
    _drop_membership(group["id"], b_id)

    for method, path, body in GROUP_ENDPOINTS:
        r = (
            getattr(client, method)(path, json=body, headers=b)
            if body is not None
            else (getattr(client, method)(path, headers=b))
        )
        assert r.status_code == 403 and r.json()["code"] == "not_member", (path, r.json())

    # 같은 그룹의 멀쩡한 멤버(a)는 여전히 정상 동작해야 한다.
    assert client.get("/family-chat/messages", headers=a).status_code == 200


def test_my_group_also_rejects_stale_membership(client, family):
    a, b, group = family
    b_id = client.get("/family-group/me", headers=b).json()["id"]
    _drop_membership(group["id"], b_id)

    r = client.get("/family-group/groups/me", headers=b)
    assert r.status_code == 403 and r.json()["code"] == "not_member"
    # 토큰 자체는 여전히 유효하므로 /me(신원 확인)는 그대로 동작해야 한다.
    assert client.get("/family-group/me", headers=b).status_code == 200


def test_stale_active_group_cannot_read_family_records_through_ai_chat(client, family, monkeypatch):
    """멤버십은 없고 active_group_id 만 남은 사용자는 AI 채팅으로도 가족 기록을 못 보고, 외부 AI 도 불리지 않는다."""
    import httpx

    from app.features.ai_assistant.knowledge import rag_chat
    from app.shared.config import settings
    from tests.helpers import allow_ai

    a, b, group = family
    client.post(
        "/ai-assistant/knowledge/items",
        json={"kind_label": "전기요금 고지서", "title": "비밀 고지서", "body_md": "청구 48,200원"},
        headers=a,
    )
    sent = []
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", lambda body: sent.append(body) or {"content": []})
    monkeypatch.setattr(httpx, "post", lambda *x, **k: sent.append("http"))
    allow_ai(client, a, monkeypatch)

    b_id = client.get("/family-group/me", headers=b).json()["id"]
    _drop_membership(group["id"], b_id)
    for path, body in (
        ("/ai-assistant/chat", {"message": "전기요금"}),
        ("/ai-assistant/knowledge/ask", {"question": "전기요금"}),
    ):
        r = client.post(path, json=body, headers=b)
        assert r.status_code == 403 and r.json()["code"] == "not_member", path
        assert "비밀" not in r.text
    assert sent == []  # 외부 AI 호출 0회
