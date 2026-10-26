"""일정 에이전트 시험(분류·답 한 호출, 질의 처리, 라우터). 실제 Anthropic 은 부르지 않고 llm.complete_json 을 가짜로 바꾼다."""

from datetime import UTC, datetime, timedelta

import pytest

from app.features.schedule import service
from app.features.schedule.agent import chat, handler, prompts, reader
from app.features.schedule.agent.schemas import AgentRequest
from app.features.schedule.schemas import EventCreate
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.llm import client as llm


class FakeLLM:
    """llm.complete_json 대신 쓰는 가짜. 호출 수와 프롬프트·모델을 센다."""

    def __init__(self):
        self.calls = []
        self.data = {"intent": "query", "reply": "", "event_ids": []}

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "model": kw.get("model"), "system": system})
        return llm.JsonResult(data=self.data, input_tokens=100, output_tokens=20, model="fake")


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete_json", f)
    monkeypatch.setattr(llm, "available", lambda: True)
    return f


@pytest.fixture
def ids(client, family):
    a, _, group = family
    user_id = client.get("/family-group/me", headers=a).json()["id"]
    return user_id, group["id"], a


def _enable(user_id, group_id):
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group_id, user_id, True)


def _add(client, headers, title, days, note=""):
    when = (datetime.now(UTC) + timedelta(days=days)).isoformat()
    r = client.post(
        "/schedule/events", json={"title": title, "starts_at": when, "note": note}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_clean_result_drops_unknown_ids_and_bad_intent():
    ok = chat.clean_result(
        {"intent": "query", "reply": " 안녕 ", "event_ids": ["a", "zzz", "a"]}, {"a", "b"}
    )
    assert ok["intent"] == "query" and ok["reply"] == "안녕" and ok["event_ids"] == ["a"]
    assert ok["need_wider"] is False and ok["keyword"] == ""
    assert chat.clean_result({"intent": "drop_all"}, {"a"})["intent"] == "not_schedule"
    empty = chat.clean_result("nope", {"a"})  # type: ignore[arg-type]
    assert empty["intent"] == "not_schedule" and empty["reply"] == "" and empty["event_ids"] == []
    wider = chat.clean_result({"need_wider": True, "keyword": " 치과 " + "가" * 50}, set())
    assert wider["need_wider"] is True and len(wider["keyword"]) == chat.MAX_KEYWORD_CHARS


def test_family_channel_does_not_read_personal_chat():
    assert "personal_chat" in reader.allowed_sources("personal")
    assert "family_chat" in reader.allowed_sources("personal")
    assert "personal_chat" not in reader.allowed_sources("family")
    assert "schedule" in reader.allowed_sources("family")


def test_read_covers_one_year_each_way(client, ids):
    user_id, group_id, _ = ids
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for title, delta in [
            ("작년 초", -400),
            ("지난달", -30),
            ("다음 달", 30),
            ("재작년 뒤", 400),
        ]:
            service.create(
                db,
                group_id,
                user_id,
                EventCreate(title=title, starts_at=now + timedelta(days=delta)),
            )
        titles = [e.title for e in reader.read(db, group_id, "personal", now).events]
    assert titles == ["지난달", "다음 달"]


def test_select_for_prompt_keeps_nearest_when_too_many(client, ids):
    user_id, group_id, _ = ids
    now = datetime.now(UTC)
    with SessionLocal() as db:
        for title, delta in [("오늘", 0), ("내일", 1), ("다음 주", 8), ("두 달 뒤", 60)]:
            service.create(
                db,
                group_id,
                user_id,
                EventCreate(title=title, starts_at=now + timedelta(days=delta)),
            )
        events = reader.read(db, group_id, "personal", now).events
    picked, omitted = reader.select_for_prompt(events, now, None, limit=2)
    assert [e.title for e in picked] == ["오늘", "내일"]
    assert omitted == 2
    assert reader.select_for_prompt(events, now, None, limit=10) == (events, 0)


def test_query_one_call_returns_text_and_event_card(client, ids, fake):
    user_id, group_id, headers = ids
    _enable(user_id, group_id)
    dentist = _add(client, headers, "치과", 1)
    _add(client, headers, "장보기", 2)
    fake.data = {"intent": "query", "reply": "내일 치과가 있어요", "event_ids": [dentist, "nope"]}
    r = client.post(
        "/schedule/agent", json={"text": "내일 일정 알려줘", "channel": "personal"}, headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "query"
    assert body["text"] == "내일 치과가 있어요"
    assert [c["type"] for c in body["cards"]] == ["event_list"]
    events = body["cards"][0]["data"]["events"]
    assert [e["id"] for e in events] == [dentist]  # 목록에 없는 id 는 버려진다
    assert events[0]["title"] == "치과" and len(events[0]["time"]) == 5
    assert len(fake.calls) == 1  # 분류와 답이 한 번의 호출
    assert fake.calls[0]["model"] == prompts.CHAT_MODEL
    assert "치과" in fake.calls[0]["prompt"] and "장보기" in fake.calls[0]["prompt"]


def test_same_question_is_served_from_cache(client, ids, fake):
    user_id, group_id, headers = ids
    _enable(user_id, group_id)
    _add(client, headers, "치과", 1)
    for _ in range(2):
        r = client.post(
            "/schedule/agent",
            json={"text": "내일 일정 알려줘", "channel": "family"},
            headers=headers,
        )
        assert r.status_code == 200
    assert len(fake.calls) == 1


def test_personal_info_is_masked_before_sending(client, ids, fake):
    user_id, group_id, headers = ids
    _enable(user_id, group_id)
    _add(client, headers, "병원 예약", 1, note="전화 010-1234-5678 로 확인")
    client.post(
        "/schedule/agent",
        json={"text": "연락처 010-9999-8888 로 일정 알려줘", "channel": "personal"},
        headers=headers,
    )
    prompt = fake.calls[0]["prompt"]
    assert "1234-5678" not in prompt and "9999-8888" not in prompt


def test_not_schedule_returns_no_cards(client, ids, fake):
    user_id, group_id, headers = ids
    _enable(user_id, group_id)
    fake.data = {"intent": "not_schedule", "reply": "", "event_ids": []}
    r = client.post(
        "/schedule/agent", json={"text": "오늘 날씨 어때?", "channel": "family"}, headers=headers
    )
    assert r.json()["intent"] == "not_schedule"
    assert r.json()["cards"] == [] and r.json()["pending_action"] is None


def test_other_intents_are_not_ready_yet(client, ids, fake):
    user_id, group_id, headers = ids
    _enable(user_id, group_id)
    fake.data = {"intent": "delete", "reply": "", "event_ids": []}
    r = client.post(
        "/schedule/agent", json={"text": "치과 지워줘", "channel": "personal"}, headers=headers
    )
    assert r.json() == {
        "intent": "delete",
        "text": handler.NOT_READY,
        "cards": [],
        "pending_action": None,
    }


def test_requires_ai_consent_and_login(client, ids, fake):
    _, _, headers = ids
    r = client.post(
        "/schedule/agent", json={"text": "일정 알려줘", "channel": "personal"}, headers=headers
    )
    assert r.status_code == 403 and r.json()["code"] == "ai_not_enabled"
    assert fake.calls == []
    assert client.post(
        "/schedule/agent", json={"text": "x", "channel": "personal"}
    ).status_code in (
        401,
        403,
    )


def test_rejects_empty_text_and_unknown_channel(client, ids, fake):
    _, _, headers = ids
    assert (
        client.post(
            "/schedule/agent", json={"text": "", "channel": "personal"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/schedule/agent", json={"text": "hi", "channel": "office"}, headers=headers
        ).status_code
        == 422
    )


def test_handle_rejects_non_member(client, ids, fake):
    _, group_id, _ = ids
    with SessionLocal() as db:
        with pytest.raises(ApiError) as e:
            handler.handle(
                db, "nobody", group_id, AgentRequest(text="일정 알려줘", channel="personal")
            )
    assert e.value.code == "not_member"
