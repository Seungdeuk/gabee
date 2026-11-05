"""가족방 @가비(audience=room)에서 일정 에이전트: 공동 일정만 다루고, 조회 결과는 방에 올릴 항목을 고르는 카드로 돌려주며,
등록은 방의 다른 구성원에게 공유한다. 메인 LLM 은 rag_chat._post, 일정 LLM 은 llm.complete_json 을 가짜로 바꾼다."""

import json
from datetime import timedelta

import pytest

from app.features.ai_assistant.knowledge import rag_chat
from app.features.schedule.agent import register
from app.shared.config import settings
from app.shared.llm import client as llm
from tests.ai_consent import enable_ai


def _tomorrow() -> str:
    return (register.today() + timedelta(days=1)).isoformat()


class FakeScheduleLLM:
    def __init__(self):
        self.calls = []
        self.data = {}

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append(prompt)
        return llm.JsonResult(data=self.data, input_tokens=100, output_tokens=20, model="fake")


@pytest.fixture
def schedule_llm(monkeypatch):
    fake = FakeScheduleLLM()
    monkeypatch.setattr(llm, "complete_json", fake)
    monkeypatch.setattr(llm, "available", lambda: True)
    return fake


def _main_llm(monkeypatch, question):
    """메인이 ask_schedule 로 question 을 넘기고, 일정 에이전트의 직통 응답을 그대로 쓴다."""

    def fake_post(body):
        if len(body["messages"]) == 1:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "ask_schedule",
                        "input": {"question": question},
                    }
                ]
            }
        last = json.loads(body["messages"][-1]["content"][0]["content"])
        return {"content": [{"type": "text", "text": last["answer"]}]}

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(rag_chat, "_post", fake_post)


def _chat(client, headers, message, audience=None):
    body = {"message": message}
    if audience:
        body["audience"] = audience
    r = client.post("/ai-assistant/chat", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _new(client, headers, title, **fields):
    body = {
        "title": title,
        "start_date": _tomorrow(),
        "start_time": "14:00:00",
        "end_time": "15:00:00",
        **fields,
    }
    r = client.post("/schedule/events", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _events(client, headers):
    return client.get("/schedule/events", params={"include_past": True}, headers=headers).json()


def _query(event_ids=(), request_ids=(), reply="찾았어요"):
    base = {
        "action": "",
        "target_id": "",
        "request_ids": list(request_ids),
        "title": "",
        "date": "",
        "start_time": "",
        "end_time": "",
        "place": "",
        "memo": "",
        "to_ids": [],
        "date_ambiguous": False,
    }
    return {"intent": "query", "reply": reply, "event_ids": list(event_ids), "request": base}


def _me(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def test_room_query_shows_only_shared_events_and_offers_a_share_select_card(
    client, family, schedule_llm, monkeypatch
):
    a, b, group = family
    enable_ai(group["id"])
    shared = _new(client, a, "치과", share_with=[_me(client, b)])
    _new(client, a, "혼자 병원")  # 나 혼자 일정
    schedule_llm.data = _query(event_ids=[shared["id"]])
    _main_llm(monkeypatch, "이번 주 일정 알려줘")
    out = _chat(client, a, "이번 주 일정 알려줘", audience="room")

    # 공유 선택 카드가 딸린 조회 답은 방에 올리지 않는다(부탁 줄에는 받는 분·수락 현황이 들어 있다). 고른 줄만 질문한 사람 이름으로 올린다
    assert out["visibility"] == "private" and out["posted_message_id"] is None
    prompt = schedule_llm.calls[-1]
    assert "치과" in prompt and "혼자 병원" not in prompt  # 공동 일정만 읽는다
    assert "[알림] 가족 채팅방" in prompt
    card = out["confirm_cards"][0]
    assert card["action"] == "share_select" and card["pending_action"] == {}
    assert [i["id"] for i in card["items"]] == [shared["id"]]
    line = card["items"][0]["line"]
    assert line.endswith("14:00 치과") and "수진" not in line  # 제목·날짜·시간만, 구성원 이름 없음


def test_personal_chat_is_unchanged(client, family, schedule_llm, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    shared = _new(client, a, "치과", share_with=[_me(client, b)])
    _new(client, a, "혼자 병원")
    schedule_llm.data = _query(event_ids=[shared["id"]])
    _main_llm(monkeypatch, "이번 주 일정 알려줘")
    out = _chat(client, a, "이번 주 일정 알려줘")
    prompt = schedule_llm.calls[-1]
    assert "치과" in prompt and "혼자 병원" in prompt and "[알림]" not in prompt
    assert out["confirm_cards"] == []  # 개인 채팅에는 공유 선택 카드가 없다


def test_room_query_without_matches_has_no_card(client, family, schedule_llm, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    _new(client, a, "치과", share_with=[_me(client, b)])
    schedule_llm.data = _query(event_ids=[], reply="공동 일정에서는 찾지 못했어요")
    _main_llm(monkeypatch, "약국 일정 있어?")
    out = _chat(client, a, "약국 일정 있어?", audience="room")
    assert out["confirm_cards"] == []


def test_room_query_can_offer_a_sent_request_too(client, family, schedule_llm, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    sent = client.post(
        "/schedule/requests",
        json={"title": "장 같이 봐줘", "start_date": _tomorrow(), "to_ids": [_me(client, b)]},
        headers=a,
    ).json()
    schedule_llm.data = _query(request_ids=[sent["id"]], reply="장 부탁이 있어요")
    _main_llm(monkeypatch, "내일 뭐 있어?")
    out = _chat(client, a, "내일 뭐 있어?", audience="room")
    items = out["confirm_cards"][0]["items"]
    assert [i["id"] for i in items] == [sent["id"]]
    assert items[0]["line"].endswith("장 같이 봐줘") and "수진" not in items[0]["line"]


def test_room_register_is_shared_with_the_other_members(client, family, schedule_llm, monkeypatch):
    a, b, group = family
    enable_ai(group["id"])
    schedule_llm.data = {
        "intent": "register",
        "reply": "",
        "event_ids": [],
        "register": {
            "title": "가족 저녁",
            "date": _tomorrow(),
            "start_time": "18:00",
            "end_time": "",
            "kind": 1,
            "place": "",
            "memo": "",
            "share_ids": [],  # 모델이 비워 둬도 방에서는 다른 구성원 전체에게 공유한다
            "date_ambiguous": False,
        },
    }
    _main_llm(monkeypatch, "내일 6시 가족 저녁 등록해줘")
    out = _chat(client, a, "내일 6시 가족 저녁 등록해줘", audience="room")
    card = out["confirm_cards"][0]
    assert card["action"] == "register" and card["shared_with"] == ["수진"]
    assert _events(client, b) == []  # 확인 전에는 공유하지 않는다

    r = client.post("/schedule/agent/confirm", json={"action": card["pending_action"]}, headers=a)
    assert r.status_code == 200, r.text
    assert [e["title"] for e in _events(client, a)] == ["가족 저녁"]  # 요청한 사람이 생성자
    assert [e["title"] for e in _events(client, b)] == [
        "가족 저녁"
    ]  # 방의 다른 구성원은 공유받는 사람(복사본)
