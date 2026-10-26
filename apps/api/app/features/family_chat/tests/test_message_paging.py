"""가족 채팅 메시지 조회(latest·before_id·after_id) 시험."""

import httpx

from app.shared.llm import client as llm
from tests.helpers import signup

URL = "/family-chat/messages"


def _post_many(client, headers, n):
    return [
        client.post(URL, json={"text": f"메시지 {i}"}, headers=headers).json()["id"]
        for i in range(1, n + 1)
    ]


def test_latest_returns_most_recent_in_ascending_order(client, family):
    a, _, _ = family
    ids = _post_many(client, a, 7)
    got = client.get(URL, params={"latest": True, "limit": 3}, headers=a).json()
    assert [m["id"] for m in got] == ids[-3:]
    assert got[0]["text"] == "메시지 5"
    assert got[0]["user_name"] == "지민"


def test_latest_with_fewer_messages_than_limit(client, family):
    a, _, _ = family
    ids = _post_many(client, a, 2)
    got = client.get(URL, params={"latest": True, "limit": 50}, headers=a).json()
    assert [m["id"] for m in got] == ids


def test_before_id_pages_back_without_gaps_or_duplicates(client, family):
    a, b, _ = family
    ids = _post_many(client, a, 5) + _post_many(client, b, 4)
    collected = []
    page = client.get(URL, params={"latest": True, "limit": 4}, headers=a).json()
    collected = [m["id"] for m in page] + collected
    while len(page) == 4:
        page = client.get(URL, params={"before_id": page[0]["id"], "limit": 4}, headers=a).json()
        assert [m["id"] for m in page] == sorted(m["id"] for m in page)
        collected = [m["id"] for m in page] + collected
    assert collected == ids


def test_before_id_excludes_the_given_id(client, family):
    a, _, _ = family
    ids = _post_many(client, a, 3)
    got = client.get(URL, params={"before_id": ids[2]}, headers=a).json()
    assert [m["id"] for m in got] == ids[:2]


def test_after_id_keeps_old_behavior(client, family):
    a, _, _ = family
    ids = _post_many(client, a, 5)
    got = client.get(URL, params={"after_id": ids[1], "limit": 2}, headers=a).json()
    assert [m["id"] for m in got] == ids[2:4]
    assert [m["id"] for m in client.get(URL, headers=a).json()] == ids


def test_combining_modes_is_rejected(client, family):
    a, _, _ = family
    ids = _post_many(client, a, 2)
    for params in (
        {"latest": True, "before_id": ids[1]},
        {"latest": True, "after_id": ids[0]},
        {"before_id": ids[1], "after_id": ids[0]},
        {"latest": True, "before_id": ids[1], "after_id": ids[0]},
    ):
        r = client.get(URL, params=params, headers=a)
        assert r.status_code == 400, params
        assert r.json()["code"] == "invalid_range"


def test_limit_bounds(client, family):
    a, _, _ = family
    _post_many(client, a, 3)
    assert client.get(URL, params={"limit": 0}, headers=a).status_code == 422
    assert client.get(URL, params={"limit": 201}, headers=a).status_code == 422
    assert client.get(URL, params={"before_id": 0}, headers=a).status_code == 422
    assert len(client.get(URL, params={"latest": True, "limit": 1}, headers=a).json()) == 1
    assert client.get(URL, params={"latest": True, "limit": 200}, headers=a).status_code == 200


def test_other_group_messages_never_appear(client, family):
    a, _, _ = family
    ids = _post_many(client, a, 3)
    outsider = signup(client, "남")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    other = client.post(URL, json={"text": "남의 얘기"}, headers=outsider).json()["id"]
    mine = client.get(URL, params={"latest": True}, headers=a).json()
    assert [m["id"] for m in mine] == ids
    theirs = client.get(URL, params={"latest": True}, headers=outsider).json()
    assert [m["id"] for m in theirs] == [other]
    assert client.get(URL, params={"before_id": other + 100}, headers=a).json() == mine


def test_requires_login_and_group(client):
    assert client.get(URL, params={"latest": True}).status_code == 401
    lonely = signup(client, "혼자")
    r = client.get(URL, params={"latest": True}, headers=lonely)
    assert r.status_code == 400
    assert r.json()["code"] == "no_group"


def test_posting_a_message_does_not_call_ai(client, family, monkeypatch):
    a, _, _ = family

    def boom(*args, **kwargs):
        raise AssertionError("AI/네트워크가 호출되면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)
    r = client.post(URL, json={"text": "안녕"}, headers=a)
    assert r.status_code == 201
    assert client.get(URL, params={"latest": True}, headers=a).status_code == 200
