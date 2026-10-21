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
