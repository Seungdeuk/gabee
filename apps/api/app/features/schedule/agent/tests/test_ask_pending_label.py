"""메인 채팅(`ask_schedule`)으로 가는 일정 조회 글이 확정 전(pending) 일정을 확정 일정과 구분해 적는지 본다.

일정 줄은 모델이 사용자에게 그대로 옮기는 글이라 상태가 없으면 '확정 전' 후보를 '이미 잡힌 일정'으로 말하게 된다(T35 compound-02).
이 시험은 글 표현만 본다: API 응답 필드·카드 필드·부탁 줄·가족 격리는 그대로여야 한다. 실제 Anthropic 은 부르지 않는다."""

from datetime import timedelta

import pytest

from app.features.schedule.agent import ask
from app.features.schedule.agent import register as register_mod
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.llm import client as llm

PENDING_MARK = "(확정 전)"


class FakeLLM:
    def __init__(self):
        self.data = {}

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        return llm.JsonResult(data=self.data, input_tokens=100, output_tokens=20, model="fake")


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete_json", f)
    monkeypatch.setattr(llm, "available", lambda: True)
    return f


@pytest.fixture
def setup(client, family):
    a, b, group = family
    ids = {
        k: client.get("/family-group/me", headers=h).json()["id"] for k, h in (("a", a), ("b", b))
    }
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group["id"], ids["a"], True)
    return a, b, ids


def _day(n: int = 3) -> str:
    return (register_mod.today() + timedelta(days=n)).isoformat()


def _event(client, headers, title, **over):
    body = {"title": title, "start_date": _day(), **over}
    r = client.post("/schedule/events", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _query(event_ids, reply="그날 일정이에요"):
    return {
        "intent": "query",
        "reply": reply,
        "event_ids": event_ids,
        "request": {
            "action": "",
            "target_id": "",
            "request_ids": [],
            "title": "",
            "date": "",
            "start_time": "",
            "end_time": "",
            "place": "",
            "memo": "",
            "to_ids": [],
            "date_ambiguous": False,
        },
    }


def _group_id(client, headers):
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


def _user(headers, client):
    from app.features.family_group.models import User

    uid = client.get("/family-group/me", headers=headers).json()["id"]
    with SessionLocal() as db:
        return db.get(User, uid)


def _ask(client, headers, text="그날 뭐 있어?"):
    with SessionLocal() as db:
        return ask.ask(db, _group_id(client, headers), _user(headers, client), text)


def _lines(reply) -> list[str]:
    return [x for x in reply.answer.splitlines() if x.startswith("- ")]


def test_pending_event_line_is_marked_and_confirmed_line_is_not(client, setup, fake):
    a, _, _ = setup
    done = _event(client, a, "치과", start_time="09:00:00", end_time="10:00:00")
    pend = _event(client, a, "할머니 댁 방문", status="pending", source="chat")
    fake.data = _query([done["id"], pend["id"]])
    lines = _lines(_ask(client, a))
    assert f"- {_day()} 09:00 치과" in lines  # 확정 일정 줄은 그대로(표시 없음)
    assert f"- {_day()} 할머니 댁 방문 {PENDING_MARK}" in lines
    assert sum(PENDING_MARK in x for x in lines) == 1


def test_confirmed_events_get_no_mark_at_all(client, setup, fake):
    a, _, _ = setup
    one = _event(client, a, "치과", start_time="09:00:00")
    two = _event(client, a, "가족 외식", status="confirmed")
    fake.data = _query([one["id"], two["id"]])
    reply = _ask(client, a)
    assert "확정 전" not in reply.answer
    assert _lines(reply) == [f"- {_day()} 09:00 치과", f"- {_day()} 가족 외식"]


def test_request_lines_are_unchanged(client, setup, fake):
    a, b, ids = setup
    sent = client.post(
        "/schedule/requests",
        json={"title": "장 같이 봐줘", "start_date": _day(), "to_ids": [ids["b"]]},
        headers=a,
    ).json()
    pend = _event(client, a, "할머니 댁 방문", status="pending", source="chat")
    data = _query([pend["id"]])
    data["request"] = data["request"] | {"request_ids": [sent["id"]]}
    fake.data = data
    lines = _lines(_ask(client, a))
    request_line = next(x for x in lines if "장 같이 봐줘" in x)
    assert "확정 전" not in request_line and "받는 분:" in request_line
    assert any(PENDING_MARK in x and "할머니 댁 방문" in x for x in lines)


def test_api_and_card_fields_do_not_carry_the_mark(client, setup, fake):
    a, _, _ = setup
    pend = _event(client, a, "할머니 댁 방문", status="pending", source="chat")
    assert pend["status"] == "pending" and "확정 전" not in pend["title"]
    fake.data = _query([pend["id"]])
    body = client.post(
        "/schedule/agent", json={"text": "그날 뭐 있어?", "channel": "personal"}, headers=a
    ).json()
    (card,) = [c for c in body["cards"] if c["type"] == "event_list"]
    (item,) = card["data"]["events"]
    assert item["status"] == "pending" and item["title"] == "할머니 댁 방문"
    listed = client.get("/schedule/events", params={"include_past": True}, headers=a).json()
    assert [(e["title"], e["status"]) for e in listed] == [("할머니 댁 방문", "pending")]


def test_other_familys_pending_event_never_appears(client, setup, fake, other_family):
    a, _, _ = setup
    mine = _event(client, a, "할머니 댁 방문", status="pending", source="chat")
    foreign = _event(client, other_family, "이웃가족 캠핑", status="pending", source="chat")
    fake.data = _query([mine["id"], foreign["id"]])
    reply = _ask(client, a)
    assert "이웃가족 캠핑" not in reply.answer
    assert f"- {_day()} 할머니 댁 방문 {PENDING_MARK}" in _lines(reply)
