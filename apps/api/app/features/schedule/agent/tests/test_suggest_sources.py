"""추천(먼저 권해드려요)의 입력 출처 확대 시험: 부탁·가족 대화 후보·개인 AI 채팅이 모델에 가는 입력에 들어가는지,
구독·결제일·돌봄·금액·지출 내역은 안 가는지, 개인정보가 가려지는지, 한 출처가 실패해도 추천이 계속되는지를 본다. 실제 Anthropic 은 부르지 않는다."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.features.schedule.agent import limits, reader, suggest, suggest_sources
from app.shared import ai_guard
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.errors import ApiError
from app.shared.llm import client as llm


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.data = {"suggestions": []}

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "max_tokens": max_tokens, "system": system})
        return llm.JsonResult(data=self.data, input_tokens=10, output_tokens=5, model="fake")


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete_json", f)
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(settings, "ai_schedule_card_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "ai_schedule_card_max_calls_per_user_per_day", 100)
    monkeypatch.setattr(settings, "ai_schedule_card_max_calls_per_group_per_day", 100)
    limits.register()
    return f


@pytest.fixture
def no_family(monkeypatch):
    """가족 대화 분석을 부르지 않는다(분석 자체는 family_chat 시험에서 본다)."""
    monkeypatch.setattr(
        suggest_sources.ai_service,
        "analysis",
        lambda *a, **k: SimpleNamespace(schedule_candidates=[], todo_candidates=[]),
    )


@pytest.fixture
def ids(client, family):
    a, b, group = family
    user_id = client.get("/family-group/me", headers=a).json()["id"]
    other_id = client.get("/family-group/me", headers=b).json()["id"]
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group["id"], user_id, True)
    return user_id, group["id"], a, b, other_id


def _day(offset: int) -> str:
    return (reader.to_local(datetime.now(UTC)).date() + timedelta(days=offset)).isoformat()


def _supply(user_id, group_id, chat=None):
    with SessionLocal() as db:
        return suggest.supply(db, user_id, group_id, chat)


def _prompt(fake) -> str:
    return fake.calls[-1]["prompt"]


def _section(prompt: str, name: str) -> str:
    """[이름] 머리글부터 다음 머리글 앞까지."""
    head = prompt.index(f"[{name}]")
    nxt = prompt.find("\n\n[", head)
    return prompt[head : nxt if nxt >= 0 else len(prompt)]


def _send(client, headers, to, **over):
    body = {"title": "병원 같이 가요", "start_date": _day(5), "to_ids": to, **over}
    r = client.post("/schedule/requests", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_prompt_has_requests_billing_family_and_chat(client, ids, fake, monkeypatch):
    user_id, group_id, a, b, other_id = ids
    _send(client, a, [other_id])  # 내가 보낸 부탁
    received = _send(client, b, [user_id], title="장 같이 봐줘")  # 아직 답하지 않은 받은 부탁
    _send(client, b, [user_id], title="이미 수락한 부탁")
    accepted = client.get("/schedule/requests", headers=a).json()
    accepted_id = next(r["id"] for r in accepted if r["title"] == "이미 수락한 부탁")
    client.post(
        f"/schedule/requests/{accepted_id}/answer",
        json={"answer": "accepted", "kind": 2},
        headers=a,
    )
    assert received["title"] == "장 같이 봐줘"
    monkeypatch.setattr(
        suggest_sources.ai_service,
        "analysis",
        lambda *args, **kw: SimpleNamespace(
            schedule_candidates=[
                SimpleNamespace(title="가족 식사", date=_day(7), time="18:00", place="한식당")
            ],
            todo_candidates=[SimpleNamespace(title="선물 사기", due=None)],
        ),
    )
    _supply(user_id, group_id, ["다음 주에 여권 갱신해야 해", "010-1234-5678 로 연락"])
    prompt = _prompt(fake)

    requests_ = _section(prompt, "부탁 목록")
    assert "병원 같이 가요" in requests_ and "내가 보낸 부탁" in requests_
    assert "장 같이 봐줘" in requests_ and "받은 부탁(답 전)" in requests_
    assert "이미 수락한 부탁" not in requests_  # 수락한 부탁은 이미 내 일정이다
    assert "결제일" not in prompt and "구독" not in prompt  # 구독 기능을 뺐다: 결제일은 읽지 않는다
    family = _section(prompt, "가족 대화에서 나온 후보")
    assert "가족 식사" in family and "일정 후보" in family and "선물 사기" in family
    assert "기한 미정" in family
    chat = _section(prompt, "내가 AI 채팅에서 한 말")
    assert "여권 갱신" in chat and "1234-5678" not in chat  # 개인정보는 가려서 보낸다
    assert "돌봄" not in prompt  # 돌봄은 읽지 않는다
    assert fake.calls[-1]["max_tokens"] >= 2000  # 입력이 늘어 생각 토큰까지 감안한 출력 한도


def test_family_analysis_failure_does_not_stop_suggestions(client, ids, fake, monkeypatch):
    user_id, group_id, headers, *_ = ids
    # 가족 분석이 실패해도 일정 같은 다른 참고 데이터가 있으면 추천은 만든다
    client.post("/schedule/events", json={"title": "치과", "start_date": _day(4)}, headers=headers)

    def broken(*a, **k):
        raise ApiError(429, "limit", "오늘 분석 한도를 다 썼어요")

    monkeypatch.setattr(suggest_sources.ai_service, "analysis", broken)
    fake.data = {
        "suggestions": [{"title": "약국에서 약 타기", "kind": 2, "date": _day(2), "place": ""}]
    }
    items, exhausted = _supply(user_id, group_id)
    assert [s.title for s in items] == ["약국에서 약 타기"] and not exhausted
    assert "(없음)" in _section(_prompt(fake), "가족 대화에서 나온 후보")


def test_clean_chat_limits_and_masks():
    lines = [f"할 일 {n}" for n in range(40)]
    assert len(suggest_sources.clean_chat(lines)) == suggest_sources.MAX_CHAT_LINES
    assert suggest_sources.clean_chat(["  ", "", "같은 말", "같은 말", None, 3]) == ["같은 말"]
    assert len(suggest_sources.clean_chat(["가" * 500])[0]) == suggest_sources.MAX_CHAT_CHARS
    out = suggest_sources.clean_chat(["내 번호는 010-9999-8888 이야"])
    assert "9999-8888" not in out[0]


def test_post_route_sends_chat_and_get_does_not(client, ids, fake, no_family):
    user_id, group_id, a, *_ = ids
    r = client.post(
        "/schedule/suggestions", json={"chat": ["다음 주에 치과 예약해야 해"]}, headers=a
    )
    assert r.status_code == 200, r.text
    assert "치과 예약해야 해" in _section(_prompt(fake), "내가 AI 채팅에서 한 말")

    assert client.post("/schedule/suggestions", headers=a).status_code == 200  # 본문 없이도 된다
    assert client.get("/schedule/suggestions", headers=a).status_code == 200


def test_post_route_validates_chat_size(client, ids, fake, no_family):
    a = ids[2]
    too_many = client.post("/schedule/suggestions", json={"chat": ["말"] * 31}, headers=a)
    too_long = client.post("/schedule/suggestions", json={"chat": ["가" * 201]}, headers=a)
    assert too_many.status_code == 422 and too_long.status_code == 422
    assert fake.calls == []  # 잘못된 요청은 AI 를 부르지 않는다


def test_chat_is_not_stored_and_pending_suggestions_skip_the_call(client, ids, fake, no_family):
    user_id, group_id, a, *_ = ids
    fake.data = {
        "suggestions": [{"title": "여권 갱신하기", "kind": 2, "date": _day(4), "place": ""}]
    }
    first = client.post("/schedule/suggestions", json={"chat": ["여권 갱신해야 해"]}, headers=a)
    assert [s["title"] for s in first.json()["suggestions"]] == ["여권 갱신하기"]
    calls = len(fake.calls)
    second = client.post("/schedule/suggestions", json={"chat": ["다른 말"]}, headers=a)
    assert len(fake.calls) == calls  # 대기 추천이 있으면 AI 를 다시 부르지 않는다
    assert [s["title"] for s in second.json()["suggestions"]] == ["여권 갱신하기"]
