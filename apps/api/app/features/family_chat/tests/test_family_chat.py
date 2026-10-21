"""가족 그룹 대화."""

from tests.helpers import signup


def test_chat_messages_are_shared_in_group_only(client, family):
    a, b, _ = family
    m1 = client.post("/family-chat/messages", json={"text": "오늘 통화했어요"}, headers=a).json()
    client.post("/family-chat/messages", json={"text": "저도요"}, headers=b)
    assert [m["text"] for m in client.get("/family-chat/messages", headers=b).json()] == [
        "오늘 통화했어요",
        "저도요",
    ]
    newer = client.get("/family-chat/messages", params={"after_id": m1["id"]}, headers=a).json()
    assert [m["user_name"] for m in newer] == ["수진"]
    outsider = signup(client, "남")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    assert client.get("/family-chat/messages", headers=outsider).json() == []
