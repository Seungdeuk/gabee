"""에이전트 체크 시험. 실제 Anthropic 은 부르지 않고 llm.complete_json 을 가짜로 바꾼다(모델의 정확도가 아니라
우리 코드가 모델 출력을 어떻게 검증하고 체크·목록으로 처리하는지를 확인한다)."""

from datetime import timedelta

import pytest

from app.features.schedule.agent import checks, register
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.llm import client as llm


def _data(action, *ids):
    return {
        "intent": "check",
        "reply": "",
        "event_ids": list(ids),
        "target_id": "",
        "check_action": action,
    }


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.data = {}

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "system": system})
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
    me = client.get("/family-group/me", headers=a).json()["id"]
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group["id"], me, True)
    return a, b


def _day(n: int = 0) -> str:
    return (register.today() + timedelta(days=n)).isoformat()


def _new(client, headers, title, n=0, **fields):
    body = {"title": title, "start_date": _day(n), **fields}
    r = client.post("/schedule/events", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _say(client, headers, text):
    return client.post(
        "/schedule/agent", json={"text": text, "channel": "personal"}, headers=headers
    )


def _checked(client, headers) -> dict:
    events = client.get("/schedule/events", params={"include_past": True}, headers=headers).json()
    return {e["title"]: e["checked"] for e in events}


def test_mark_appointment_and_todo_with_matching_words(client, setup, fake):
    a, _ = setup
    visit = _new(client, a, "치과", start_time="14:00:00", end_time="15:00:00", kind=1)
    chore = _new(client, a, "세탁물 찾기", kind=2)
    fake.data = _data("mark", visit["id"])
    body = _say(client, a, "치과 확인했어").json()
    assert body["intent"] == "check" and body["text"] == "'치과' 확인했어요"  # 약속은 확인
    assert body["cards"][0]["data"]["events"][0]["checked"] is True
    assert body["pending_action"] is None  # 확인 카드를 거치지 않는다
    fake.data = _data("mark", chore["id"])
    assert (
        _say(client, a, "세탁물 찾기 다 했어").json()["text"] == "'세탁물 찾기' 완료했어요"
    )  # 할 일은 완료
    assert _checked(client, a) == {"치과": True, "세탁물 찾기": True}
    assert len(fake.calls) == 2


def test_mark_several_and_unmark(client, setup, fake):
    a, _ = setup
    one = _new(client, a, "치과", kind=1)
    two = _new(client, a, "장보기", kind=2)
    fake.data = _data("mark", one["id"], two["id"], "zzz")  # 목록에 없는 id 는 버려진다
    text = _say(client, a, "오늘 일정 다 확인했어").json()["text"]
    assert "'치과' 확인했어요" in text and "'장보기' 완료했어요" in text
    fake.data = _data("unmark", one["id"])
    body = _say(client, a, "치과 확인 취소해줘").json()
    assert body["text"] == "'치과' 확인을 취소했어요"
    assert _checked(client, a) == {"치과": False, "장보기": True}


def test_unknown_target_is_not_acted_on(client, setup, fake):
    a, _ = setup
    _new(client, a, "치과", kind=1)
    fake.data = _data("mark", "zzz")
    body = _say(client, a, "여행 확인했어").json()
    assert body["text"] == checks.NOT_FOUND_TEXT and body["cards"] == []
    assert _checked(client, a) == {"치과": False}
    fake.data = _data("mark")  # 대상이 없는 mark
    assert _say(client, a, "확인했어").json()["text"] == checks.NOT_FOUND_TEXT


def test_list_unchecked_today_without_llm_search(client, setup, fake):
    a, _ = setup
    done = _new(client, a, "아침 약", kind=2)
    _new(client, a, "치과", start_time="14:00:00", end_time="15:00:00", kind=1)
    _new(client, a, "장보기", kind=2)
    _new(client, a, "내일 일정", n=1, kind=1)
    client.put(f"/schedule/events/{done['id']}/checked", json={"checked": True}, headers=a)
    fake.data = _data("list")
    body = _say(client, a, "확인 안 한 일정 보여줘").json()
    titles = [e["title"] for e in body["cards"][0]["data"]["events"]]
    assert titles == ["장보기", "치과"]  # 오늘 것 중 체크 안 한 것만, 시간순(시간 없는 것은 0시)
    assert "오늘" in body["text"] and "2개" in body["text"]
    assert all(not e["checked"] for e in body["cards"][0]["data"]["events"])


def test_list_when_everything_is_checked(client, setup, fake):
    a, _ = setup
    e = _new(client, a, "치과", kind=1)
    client.put(f"/schedule/events/{e['id']}/checked", json={"checked": True}, headers=a)
    fake.data = _data("list")
    body = _say(client, a, "확인 안 한 일정 있어?").json()
    assert body["cards"] == [] and "없어요" in body["text"]


def test_missing_action_falls_back_by_target(client, setup, fake):
    a, _ = setup
    e = _new(client, a, "치과", kind=1)
    fake.data = _data("", e["id"])  # 모델이 action 을 비웠지만 대상이 있다 → mark
    assert _say(client, a, "치과 확인").json()["text"] == "'치과' 확인했어요"
    fake.data = _data("")  # 대상도 없다 → 확인하지 않은 일정 보기
    assert "확인하지 않은 일정이 없어요" in _say(client, a, "확인 현황").json()["text"]


def test_check_only_touches_my_own_rows(client, setup, fake):
    a, b = setup
    mine = _new(
        client,
        a,
        "치과",
        kind=1,
        share_with=[client.get("/family-group/me", headers=b).json()["id"]],
    )
    fake.data = _data("mark", mine["id"])
    _say(client, a, "치과 확인했어")
    assert _checked(client, a) == {"치과": True}
    assert _checked(client, b) == {"치과": False}  # 공유받은 사람의 복사본은 그대로
