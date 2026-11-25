"""가족방(channel=family) 일정 Agent 의 권한 격리(P0, 2026-11-25). 실제 Anthropic 은 부르지 않고 llm.complete_json 을 가짜로 바꾼다.

가족방 @가비 의 답은 방에 저장되어 방 구성원 모두가 본다. 그래서 가족방에서 일정 Agent 가 모델에 주거나 답·카드에 싣는 부탁·일정은
**방 구성원 모두가 원래 볼 수 있는 것**으로 한정한다(서버가 모델 호출 전에 거른다. 메인 프롬프트·NER 가림에 기대지 않는다).
- 부탁: 보낸 사람과 받는 사람 전원이 가족 구성원 전원을 덮을 때만(나머지는 제목·id·날짜·관계 모두 제외)
- 일정: 나와 공유 관계에 있는 사람이 가족 구성원 전원을 덮을 때만(일부에게만 공유한 일정 제외)
개인 채팅의 기존 동작(내가 보냈거나 받은 부탁, 내 일정 전체)은 그대로다.

재현: 통합 평가(595412f1) chat-02 r1 에서 가족방 일정 Agent 가 지민→수진 부탁 "마트에서 쌀 사다 주기" 를 방 답에 실었다.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.features.schedule.agent import register as register_mod
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

PRIVATE_TITLE = "마트에서 쌀 사다 주기 비밀"
ALL_TITLE = "다 같이 대청소 하기"
PART_EVENT = "둘만 아는 상담 일정"
ALL_EVENT = "온 가족 외식 일정"


def _req_query(ids, reply=""):
    base = {
        "action": "query", "target_id": "", "request_ids": ids, "title": "", "date": "",
        "start_time": "", "end_time": "", "place": "", "memo": "", "to_ids": [], "date_ambiguous": False,
    }  # fmt: skip
    return {"intent": "request", "reply": reply, "event_ids": [], "request": base}


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.data = {"intent": "query", "reply": "", "event_ids": []}

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "system": system})
        data = self.data(prompt) if callable(self.data) else self.data
        return llm.JsonResult(data=data, input_tokens=100, output_tokens=20, model="fake")


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM()
    monkeypatch.setattr(llm, "complete_json", f)
    monkeypatch.setattr(llm, "available", lambda: True)
    return f


@pytest.fixture
def three(client, family):
    """가족 구성원 A(지민)·B(수진)·C(민수)."""
    a, b, group = family
    c = signup(client, "민수")
    join_family(client, a, group["invite_code"], c)
    ids = {
        k: client.get("/family-group/me", headers=h).json()["id"]
        for k, h in (("a", a), ("b", b), ("c", c))
    }
    with SessionLocal() as db:
        for uid in ids.values():
            ai_guard.set_enabled(db, group["id"], uid, True)
    return a, b, c, ids


def _day(n=3):
    return (register_mod.today() + timedelta(days=n)).isoformat()


def _send(client, headers, to, title):
    r = client.post(
        "/schedule/requests",
        json={"title": title, "start_date": _day(), "to_ids": to},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _event(client, headers, title, share_to=()):
    when = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    r = client.post(
        "/schedule/events",
        json={"title": title, "starts_at": when, "share_with": list(share_to)},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _say(client, headers, text, channel):
    return client.post("/schedule/agent", json={"text": text, "channel": channel}, headers=headers)


def _prompt(fake):
    return fake.calls[-1]["prompt"]


# ---------- 부탁 ----------
def test_a_private_request_between_two_members_is_not_given_to_the_model_in_the_family_room(
    client, three, fake
):
    a, b, c, ids = three
    private = _send(client, a, [ids["b"]], PRIVATE_TITLE)  # A→B, C 는 볼 수 없다
    _say(client, b, "장보기 목록 알려줘", "family")
    prompt = _prompt(fake)
    assert PRIVATE_TITLE not in prompt and private["id"] not in prompt  # 제목·id 모두 없다


def test_a_request_shared_with_only_some_members_is_excluded_in_the_family_room(
    client, three, fake
):
    a, b, c, ids = three
    partial = _send(client, a, [ids["b"]], "일부만 아는 부탁")
    _say(client, a, "내 부탁 알려줘", "family")  # 보낸 사람이 물어도 방에는 C 가 있다
    assert "일부만 아는 부탁" not in _prompt(fake) and partial["id"] not in _prompt(fake)


def test_a_request_visible_to_every_member_is_still_listed_in_the_family_room(client, three, fake):
    a, b, c, ids = three
    everyone = _send(client, a, [ids["b"], ids["c"]], ALL_TITLE)  # 가족 전원(A 보냄, B·C 받음)
    _say(client, b, "부탁 알려줘", "family")
    prompt = _prompt(fake)
    assert ALL_TITLE in prompt and everyone["id"] in prompt


def test_personal_chat_still_lists_my_sent_and_received_requests(client, three, fake):
    a, b, c, ids = three
    private = _send(client, a, [ids["b"]], PRIVATE_TITLE)
    _say(client, b, "내가 받은 부탁 알려줘", "personal")
    assert PRIVATE_TITLE in _prompt(fake) and private["id"] in _prompt(fake)
    _say(client, a, "내가 보낸 부탁 알려줘", "personal")
    assert PRIVATE_TITLE in _prompt(fake)


def test_a_model_answer_that_names_a_private_request_id_is_dropped_in_the_family_room(
    client, three, fake
):
    """모델이 허용 목록에 없는 부탁 id 를 골라도 서버가 버려 카드·직접 답에 실리지 않는다."""
    a, b, c, ids = three
    private = _send(client, a, [ids["b"]], PRIVATE_TITLE)
    fake.data = _req_query([private["id"]])
    body = _say(client, b, "그 부탁 알려줘", "family").json()
    dumped = str(body)
    assert PRIVATE_TITLE not in dumped and private["id"] not in dumped


def test_another_familys_request_is_never_listed(client, three, fake, other_family):
    a, b, c, ids = three
    outsider = other_family
    out_id = client.get("/family-group/me", headers=outsider).json()["id"]
    assert out_id not in ids.values()
    _send(client, a, [ids["b"], ids["c"]], ALL_TITLE)
    _say(client, b, "부탁 알려줘", "family")
    assert out_id not in _prompt(fake)


# ---------- 일정 ----------
def test_an_event_shared_with_only_some_members_is_excluded_in_the_family_room(client, three, fake):
    a, b, c, ids = three
    part = _event(client, a, PART_EVENT, share_to=[ids["b"]])  # A·B 만
    _event(client, a, ALL_EVENT, share_to=[ids["b"], ids["c"]])  # 가족 전원
    _say(client, a, "이번 주 일정 알려줘", "family")
    prompt = _prompt(fake)
    assert PART_EVENT not in prompt and part["id"] not in prompt
    assert ALL_EVENT in prompt


def test_personal_chat_still_shows_partially_shared_and_private_events(client, three, fake):
    a, b, c, ids = three
    _event(client, a, PART_EVENT, share_to=[ids["b"]])
    _event(client, a, "나만 보는 일정")
    _say(client, a, "이번 주 일정 알려줘", "personal")
    prompt = _prompt(fake)
    assert PART_EVENT in prompt and "나만 보는 일정" in prompt


def test_a_model_answer_naming_a_partially_shared_event_is_dropped_in_the_family_room(
    client, three, fake
):
    a, b, c, ids = three
    part = _event(client, a, PART_EVENT, share_to=[ids["b"]])
    fake.data = {"intent": "query", "reply": "일정이에요", "event_ids": [part["id"]]}
    body = _say(client, a, "그 일정 알려줘", "family").json()
    assert PART_EVENT not in str(body) and part["id"] not in str(body)


def test_the_wider_retry_keeps_the_room_scope(client, three, fake):
    """모델이 목록이 부족하다며 다시 묻게 해도(need_wider) 두 번째 목록도 같은 권한으로 거른 일정에서만 만든다."""
    a, b, c, ids = three
    _event(client, a, PART_EVENT, share_to=[ids["b"]])
    _event(client, a, ALL_EVENT, share_to=[ids["b"], ids["c"]])
    answers = iter(
        [
            {
                "intent": "query",
                "reply": "",
                "event_ids": [],
                "need_wider": True,
                "keyword": "일정",
            },
            {"intent": "query", "reply": "확인했어요", "event_ids": []},
        ]
    )
    fake.data = lambda prompt: next(answers)
    _say(client, a, "일정 다 찾아줘", "family")
    assert len(fake.calls) == 2
    assert all(PART_EVENT not in c["prompt"] for c in fake.calls)
    assert ALL_EVENT in fake.calls[-1]["prompt"]


def test_a_cancel_aimed_at_a_private_request_from_the_family_room_finds_nothing(
    client, three, fake
):
    """방에서 모델이 비공개 부탁 id 로 취소·수정을 고르면 허용 목록 밖이라 대상이 비고, 제목이 답·카드에 실리지 않는다(DB 도 그대로)."""
    a, b, c, ids = three
    private = _send(client, a, [ids["b"]], PRIVATE_TITLE)
    data = _req_query([])
    data["request"].update(action="cancel", target_id=private["id"])
    fake.data = data
    body = _say(client, a, "그 부탁 취소해줘", "family").json()
    assert PRIVATE_TITLE not in str(body) and private["id"] not in str(body)
    assert body.get("pending_action") is None
    mine = client.get("/schedule/requests", headers=a).json()
    assert any(r["id"] == private["id"] and not r["canceled"] for r in mine)


def test_a_two_member_family_still_sees_shared_events_and_requests_in_the_family_room(
    client, family, fake
):
    """구성원이 둘이면 서로 공유한 일정·부탁은 방 구성원 전원이 보는 것이라 그대로 나온다(정상 공동 일정 조회 유지)."""
    a, b, group = family
    ids = {
        k: client.get("/family-group/me", headers=h).json()["id"] for k, h in (("a", a), ("b", b))
    }
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group["id"], ids["a"], True)
    _event(client, a, ALL_EVENT, share_to=[ids["b"]])
    req = _send(client, a, [ids["b"]], ALL_TITLE)
    _say(client, a, "일정이랑 부탁 알려줘", "family")
    prompt = _prompt(fake)
    assert ALL_EVENT in prompt and ALL_TITLE in prompt and req["id"] in prompt


# ---------- 선택(되묻기) 상태·초안이 채널을 넘지 않는다 ----------
def _req_cancel(target):
    data = _req_query([])
    data["request"].update(action="cancel", target_id=target)
    return data


def test_a_personal_request_choice_is_not_resolved_by_a_later_family_room_message(
    client, three, fake
):
    """개인 채팅에서 같은 제목 부탁 둘을 두고 되물은 상태가 같은 사람의 가족방 말('첫 번째')로 이어지지 않는다(제목·카드·쓰기 없음)."""
    a, b, c, ids = three
    first = _send(client, a, [ids["b"]], PRIVATE_TITLE)
    second = client.post(
        "/schedule/requests",
        json={"title": PRIVATE_TITLE, "start_date": _day(10), "to_ids": [ids["b"]]},
        headers=a,
    ).json()
    fake.data = _req_cancel(first["id"])
    asked = _say(client, a, "그 부탁 취소해줘", "personal").json()
    assert asked["pending_action"] is None and asked["cards"]  # 개인 채팅에서는 되묻는다(정상)
    fake.data = {"intent": "not_schedule", "reply": "", "event_ids": []}
    body = _say(client, a, "첫 번째", "family").json()
    dumped = str(body)
    assert PRIVATE_TITLE not in dumped and first["id"] not in dumped and second["id"] not in dumped
    assert body.get("pending_action") is None
    assert not any(r["canceled"] for r in client.get("/schedule/requests", headers=a).json())


def test_a_personal_event_choice_cannot_delete_or_reveal_an_event_from_the_family_room(
    client, three, fake
):
    a, b, c, ids = three
    keep = _event(client, a, "나만 아는 병원 일정")
    _event(client, a, "나만 아는 상담 일정")
    fake.data = {
        "intent": "delete",
        "reply": "",
        "event_ids": [],
        "target_id": "",
        "target_unnamed": True,
    }
    assert _say(client, a, "그거 지워줘", "personal").json()["text"] == "어느 일정인가요?"
    fake.data = {"intent": "not_schedule", "reply": "", "event_ids": []}
    body = _say(client, a, "첫 번째", "family").json()
    assert "나만 아는" not in str(body) and "지웠어요" not in str(body)
    titles = {e["title"] for e in client.get("/schedule/events", headers=a).json()}
    assert {"나만 아는 병원 일정", "나만 아는 상담 일정"} <= titles and keep["id"]


def test_the_same_personal_choice_still_works_in_the_personal_chat(client, three, fake):
    """정상 기능 유지: 개인 채팅의 되묻기는 개인 채팅의 답으로 이어진다."""
    a, b, c, ids = three
    _event(client, a, "나만 아는 병원 일정")
    keep = _event(client, a, "나만 아는 상담 일정")
    fake.data = {
        "intent": "delete",
        "reply": "",
        "event_ids": [],
        "target_id": "",
        "target_unnamed": True,
    }
    assert _say(client, a, "그거 지워줘", "personal").json()["text"] == "어느 일정인가요?"
    done = _say(client, a, "첫 번째", "personal").json()
    assert "지웠어요" in done["text"]
    assert keep["id"] in {e["id"] for e in client.get("/schedule/events", headers=a).json()}


def test_an_app_sent_choice_is_ignored_in_the_family_room(client, three, fake):
    """앱이 돌려보낸 선택(request.choice)에 비공개 부탁 id 가 들어 있어도 가족방에서는 쓰지 않는다(가족방은 선택 카드를 보여 주지 않는다)."""
    a, b, c, ids = three
    private = _send(client, a, [ids["b"]], PRIVATE_TITLE)
    fake.data = {"intent": "not_schedule", "reply": "", "event_ids": []}
    body = client.post(
        "/schedule/agent",
        json={
            "text": "첫 번째",
            "channel": "family",
            "choice": {"kind": "request_cancel", "event_ids": [private["id"]]},
        },
        headers=a,
    ).json()
    assert PRIVATE_TITLE not in str(body) and private["id"] not in str(body)
    assert body.get("pending_action") is None


def test_a_personal_draft_is_not_continued_in_the_family_room():
    """개인 채팅에서 되묻던 초안(제목 등)은 같은 사람의 가족방 요청에 이어지지 않고, 개인 채팅에서는 그대로 이어진다."""
    from app.features.schedule.agent import ask as schedule_ask
    from app.features.schedule.agent.schemas import AgentResponse, Draft

    draft = Draft.model_validate({"mode": "event", "title": "나만 아는 비밀 약속"})
    schedule_ask._keep_draft(
        "g-1", "u-1", AgentResponse(intent="register", draft=draft), "personal"
    )
    assert schedule_ask._take_draft("g-1", "u-1", "family") is None
    kept = schedule_ask._take_draft("g-1", "u-1", "personal")
    assert kept is not None and kept.title == "나만 아는 비밀 약속"
