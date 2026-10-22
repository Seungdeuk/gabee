"""AI 채팅과 사진 올리기."""


def test_ai_chat_falls_back_without_api_key(client, family):
    a, _, _ = family
    r = client.post("/ai-assistant/chat", json={"message": "오늘 일정 알려줘"}, headers=a).json()
    assert r["source"] == "fallback" and r["reply"]
    assert client.post("/ai-assistant/chat", json={"message": ""}, headers=a).status_code == 422


def test_photo_upload_rules(client, family):
    a, b, _ = family
    ok = client.post(
        "/ai-assistant/photos",
        files={"file": ("a.jpg", b"\xff\xd8\xff" + b"0" * 20, "image/jpeg")},
        headers=a,
    )
    assert ok.status_code == 201 and ok.json()["status"] == "received"
    assert (
        client.post(
            "/ai-assistant/photos", files={"file": ("a.gif", b"GIF89a", "image/gif")}, headers=a
        ).json()["code"]
        == "unsupported_type"
    )
    assert (
        client.post(
            "/ai-assistant/photos", files={"file": ("a.jpg", b"", "image/jpeg")}, headers=a
        ).json()["code"]
        == "empty_file"
    )
    assert [p["filename"] for p in client.get("/ai-assistant/photos", headers=b).json()] == [
        "a.jpg"
    ]


def test_chat_uses_family_records_and_returns_sources(client, family, monkeypatch):
    from app.features.ai_assistant.knowledge import rag_chat
    from app.shared.config import settings

    a, _, _ = family
    client.post(
        "/ai-assistant/knowledge/items",
        json={
            "kind_label": "전기요금 고지서",
            "title": "10월 전기요금",
            "body_md": "# 10월 전기요금\n분류: 전기요금 고지서\n- 청구금액 48,200원",
        },
        headers=a,
    )
    steps = []

    def fake_post(body):
        steps.append(1)
        if len(steps) == 1:
            call = {
                "type": "tool_use",
                "id": "t",
                "name": "search_knowledge",
                "input": {"query": "전기요금"},
            }
            return {"content": [call]}
        return {"content": [{"type": "text", "text": "「10월 전기요금」은 48,200원이에요."}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    r = client.post("/ai-assistant/chat", json={"message": "전기요금 얼마야"}, headers=a).json()
    assert r["source"] == "ai" and "48,200원" in r["reply"]
    assert [(s["n"], s["title"]) for s in r["sources"]] == [(1, "10월 전기요금")]


def test_chat_without_a_family_group_still_answers(client):
    from tests.helpers import signup

    lone = signup(client, "혼자")
    r = client.post("/ai-assistant/chat", json={"message": "안녕"}, headers=lone).json()
    assert r["source"] == "fallback" and r["reply"] and r["sources"] == []


def test_chat_history_is_sent_in_order_and_limit_is_enforced(client, family, monkeypatch):
    from app.features.ai_assistant import service
    from app.features.ai_assistant.knowledge import rag_chat
    from app.shared.config import settings

    a, _, _ = family
    seen = []

    def fake_post(body):
        seen.append(body["messages"])
        return {"content": [{"type": "text", "text": "네, 알겠어요."}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)
    monkeypatch.setattr(service, "DAILY_LIMIT", 2)
    service._calls.clear()
    history = [
        {"role": "assistant", "text": "안녕하세요"},  # user 로 시작하지 않는 앞부분은 버린다
        {"role": "user", "text": "전기요금 알려줘"},
        {"role": "assistant", "text": "48,200원이에요"},
    ]
    body = {"message": "그럼 수도는?", "history": history}
    assert client.post("/ai-assistant/chat", json=body, headers=a).status_code == 200
    assert [(m["role"], m["content"]) for m in seen[0]] == [
        ("user", "전기요금 알려줘"),
        ("assistant", "48,200원이에요"),
        ("user", "그럼 수도는?"),
    ]
    assert (
        client.post("/ai-assistant/chat", json={"message": "한 번 더"}, headers=a).status_code
        == 200
    )
    third = client.post("/ai-assistant/chat", json={"message": "또?"}, headers=a)
    assert third.status_code == 429 and third.json()["code"] == "daily_limit"
    too_long = {"message": "a", "history": [{"role": "user", "text": "x"}] * 11}
    assert client.post("/ai-assistant/chat", json=too_long, headers=a).status_code == 422
