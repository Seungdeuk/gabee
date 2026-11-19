"""에이전트 부탁(함께하기) 시험. 실제 Anthropic 은 부르지 않고 llm.complete_json 을 가짜로 바꾼다(모델의 정확도가 아니라
우리 코드가 모델 출력을 어떻게 검증하고 확인 카드·실행·개인정보 규칙으로 처리하는지를 확인한다)."""

from datetime import timedelta

import pytest

from app.features.schedule.agent import ask, request_flow
from app.features.schedule.agent import register as register_mod
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import join_family, signup


def _req(action, **fields):
    base = {
        "action": action,
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
    }
    base.update(fields)
    return {"intent": "request", "reply": fields.pop("reply", ""), "event_ids": [], "request": base}


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
    c = signup(client, "민수")
    join_family(client, a, group["invite_code"], c)
    ids = {
        k: client.get("/family-group/me", headers=h).json()["id"]
        for k, h in (("a", a), ("b", b), ("c", c))
    }
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group["id"], ids["a"], True)
    return a, b, c, ids


def _day(n: int = 3) -> str:
    return (register_mod.today() + timedelta(days=n)).isoformat()


def _send(client, headers, to, **over):
    body = {"title": "장 같이 봐줘", "start_date": _day(), "to_ids": to, **over}
    r = client.post("/schedule/requests", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _answer(client, headers, rid, answer="accepted", kind=2):
    return client.post(
        f"/schedule/requests/{rid}/answer", json={"answer": answer, "kind": kind}, headers=headers
    )


def _say(client, headers, text, channel="personal"):
    return client.post("/schedule/agent", json={"text": text, "channel": channel}, headers=headers)


def _confirm(client, headers, action):
    return client.post("/schedule/agent/confirm", json={"action": action}, headers=headers)


def _requests(client, headers):
    return client.get("/schedule/requests", headers=headers).json()


def _events(client, headers):
    return client.get("/schedule/events", params={"include_past": True}, headers=headers).json()


# ---------- 상세·질의 ----------
def test_sender_query_shows_names_and_hides_declined_as_waiting(client, setup, fake):
    a, b, c, ids = setup
    sent = _send(client, a, [ids["b"], ids["c"]])
    _answer(client, b, sent["id"])
    _answer(client, c, sent["id"], answer="declined", kind=None)
    fake.data = _req("query", request_ids=[sent["id"]]) | {"reply": "엄마가 수락했어요"}
    body = _say(client, a, "장 부탁 누가 수락했어?").json()
    assert body["intent"] == "request" and body["text"] == "엄마가 수락했어요"
    card = body["cards"][0]
    assert card["type"] == "request_list"
    got = {r["status"] for r in card["data"]["requests"][0]["recipients"]}
    assert got == {"수락", "대기"}  # 어렵다고 답한 사람은 보낸 사람에게 대기로 보인다
    line = next(x for x in fake.calls[-1]["prompt"].splitlines() if x.startswith(sent["id"]))
    assert f"{ids['b']}=수락" in line and f"{ids['c']}=대기" in line and "내가 보냄" in line
    assert "어려움" not in line and "declined" not in line


def test_receiver_prompt_does_not_expose_other_recipients(client, setup, fake):
    a, b, c, ids = setup
    sent = _send(client, a, [ids["b"], ids["c"]])
    fake.data = _req("query", request_ids=[sent["id"]]) | {"reply": "아직 답하지 않았어요"}
    _say(client, b, "내가 받은 부탁 알려줘")
    line = next(x for x in fake.calls[-1]["prompt"].splitlines() if x.startswith(sent["id"]))
    assert "받음" in line and f"보낸이:{ids['a']}" in line
    assert ids["c"] not in line  # 같이 받은 사람은 모른다
    _answer(client, c, sent["id"])
    _say(client, b, "내가 받은 부탁 알려줘")
    line = next(x for x in fake.calls[-1]["prompt"].splitlines() if x.startswith(sent["id"]))
    assert f"수락:{ids['c']}" in line  # 수락한 사람은 보인다
    body = _say(client, b, "내가 받은 부탁 알려줘").json()
    card = body["cards"][0]["data"]["requests"][0]
    assert card["role"] == "received" and len(card["accepted"]) == 1 and "recipients" not in card


def test_query_drops_unknown_request_ids(client, setup, fake):
    a, _, _, ids = setup
    _send(client, a, [ids["b"]])
    fake.data = _req("query", request_ids=["zzzz"]) | {"reply": "찾지 못했어요"}
    body = _say(client, a, "그 부탁 알려줘").json()
    assert body["cards"] == []


# ---------- 보내기 ----------
def test_create_sends_immediately_and_announces(client, setup, fake):
    a, b, _, ids = setup
    fake.data = _req(
        "create", title="병원 같이 가요", date=_day(), start_time="10:00", to_ids=[ids["b"]]
    )
    body = _say(client, a, "수진한테 병원 같이 가달라고 부탁해줘").json()
    # 확인 카드 없이 바로 보내고 날짜·시간·제목·받는 사람을 안내한다(정책 #10·#20)
    assert body["pending_action"] is None and body["cards"][0]["type"] == "request_list"
    assert (
        "'병원 같이 가요' 부탁을 수진에게 보냈어요." in body["text"]
        and "10:00~11:00" in body["text"]
    )
    assert body["text"] != "부탁을 보냈어요."
    got = _requests(client, b)
    assert [x["title"] for x in got] == ["병원 같이 가요"] and got[0]["start_time"] == "10:00:00"
    assert got[0]["end_time"] == "11:00:00"  # 시작만 말하면 한 시간 뒤


def test_create_puts_extra_explanation_in_memo_field(client, setup, fake):
    a, b, _, ids = setup
    fake.data = _req(
        "create", title="마트 장보기", date=_day(), memo="우유랑 계란", to_ids=[ids["b"]]
    )
    _say(client, a, "수진한테 마트 가서 우유랑 계란 사다 달라고 부탁해줘")
    assert _requests(client, b)[0]["memo"] == "우유랑 계란"
    assert "memo(제목으로 정리한 말 밖의 부연설명" in fake.calls[-1]["system"]  # #26 프롬프트 규칙


def test_create_asks_for_missing_recipient_then_continues(client, setup, fake):
    a, b, _, ids = setup
    fake.data = _req("create", title="장 봐줘", date=_day())
    first = _say(client, a, "내일 장 봐달라고 부탁해줘").json()
    assert (
        "누구에게" in first["text"]
        and first["draft"]["mode"] == "request"
        and first["draft"]["asks"] == 1
    )
    assert first["pending_action"] is None
    fake.data = _req("create", to_ids=[ids["b"]])  # 초안에 누구만 채워 답한다
    body = _client_say_with_draft(client, a, "수진한테", first["draft"])
    assert body["pending_action"] is None and "'장 봐줘' 부탁을 수진에게 보냈어요." in body["text"]
    assert [x["title"] for x in _requests(client, b)] == ["장 봐줘"]
    assert "종류: 부탁" in fake.calls[-1]["prompt"]


def _client_say_with_draft(client, headers, text, draft):
    r = client.post(
        "/schedule/agent",
        json={"text": text, "channel": "personal", "draft": draft},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_create_gives_up_after_two_questions(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _req("create", title="장 봐줘")
    first = _say(client, a, "장 봐달라고 부탁해줘").json()
    second = _client_say_with_draft(client, a, "어", first["draft"])
    third = _client_say_with_draft(client, a, "음", second["draft"])
    assert third["text"] == request_flow.GIVE_UP_TEXT and third["draft"] is None


# ---------- 받는 사람 바꾸기 ----------
def test_edit_adds_and_removes_recipients_immediately(client, setup, fake):
    a, b, c, ids = setup
    sent = _send(client, a, [ids["b"]])
    fake.data = _req("edit", target_id=sent["id"], to_ids=[ids["b"], ids["c"]])
    body = _say(client, a, "장 부탁에 민수도 넣어줘").json()
    assert body["pending_action"] is None  # 받는 사람 변경은 카드 없이 바로(정책 #10)
    assert "'장 같이 봐줘' 부탁의 받는 사람을" in body["text"] and "민수" in body["text"]
    assert len(_requests(client, c)) == 1

    fake.data = _req("edit", target_id=sent["id"], to_ids=[ids["c"]])
    body = _say(client, a, "수진은 빼줘").json()
    assert "수락한 분" not in body["text"]  # 수락 전이라 일정 삭제 안내는 없다
    assert _requests(client, b) == []


def test_edit_removing_accepted_deletes_their_event_and_says_so(client, setup, fake):
    a, b, c, ids = setup
    sent = _send(client, a, [ids["b"], ids["c"]])
    _answer(client, b, sent["id"])
    assert len(_events(client, b)) == 1
    fake.data = _req("edit", target_id=sent["id"], to_ids=[ids["c"]])
    body = _say(client, a, "수진 빼줘").json()
    assert body["pending_action"] is None
    assert "수락한 분을 제외해서 그 일정도 같이 사라졌어요" in body["text"]
    assert _events(client, b) == []


# ---------- 메모 바꾸기(#25) ----------
def test_edit_memo_works_after_accept_and_new_accepts_get_the_new_memo(client, setup, fake):
    a, b, c, ids = setup
    sent = _send(client, a, [ids["b"], ids["c"]], memo="처음 메모")
    _answer(client, b, sent["id"])  # b 는 이미 수락했다
    fake.data = _req("edit", target_id=sent["id"], memo="우유 두 개")
    body = _say(client, a, "장 부탁 메모를 우유 두 개로 바꿔줘").json()
    assert body["pending_action"] is None and "부탁의 메모를 바꿨어요" in body["text"]
    assert body["cards"][0]["data"]["requests"][0]["memo"] == "우유 두 개"
    assert next(e for e in _events(client, b))["memo"].startswith(
        "처음 메모"
    )  # 수락한 사람의 일정은 독립
    _answer(client, c, sent["id"])  # 고친 뒤에 수락하면 새 메모가 들어간다
    assert _events(client, c)[0]["memo"] == "우유 두 개\n함께하기에서 등록된 일정입니다."


def test_edit_memo_same_and_with_recipients(client, setup, fake):
    a, b, c, ids = setup
    sent = _send(client, a, [ids["b"]], memo="그대로")
    fake.data = _req("edit", target_id=sent["id"], memo="그대로")
    assert _say(client, a, "메모 그대로").json()["text"] == request_flow.MEMO_SAME_TEXT
    fake.data = _req("edit", target_id=sent["id"], memo="새 메모", to_ids=[ids["b"], ids["c"]])
    body = _say(client, a, "메모 바꾸고 민수도 넣어줘").json()
    assert "메모를 바꿨어요" in body["text"] and "받는 사람을" in body["text"]
    assert len(_requests(client, c)) == 1 and _requests(client, c)[0]["memo"] == "새 메모"
    fake.data = _req(
        "edit", target_id=sent["id"], memo="x", place="서울병원"
    )  # 장소는 여전히 못 바꾼다
    assert _say(client, a, "장소도 바꿔줘").json()["text"] == request_flow.CONTENT_FIXED_TEXT
    fake.data = _req("edit", target_id=sent["id"], memo="x")
    assert _say(client, b, "메모 바꿔줘").json()["text"] == request_flow.NOT_SENDER_EDIT


def test_edit_rules(client, setup, fake):
    a, b, _, ids = setup
    sent = _send(client, a, [ids["b"]])
    fake.data = _req("edit", target_id=sent["id"], title="새 제목")
    assert _say(client, a, "부탁 제목 바꿔줘").json()["text"] == request_flow.CONTENT_FIXED_TEXT
    fake.data = _req("edit", target_id=sent["id"], to_ids=[ids["b"]])
    assert _say(client, a, "수진 넣어줘").json()["text"] == request_flow.NOTHING_TEXT
    fake.data = _req("edit", target_id=sent["id"], to_ids=[])
    assert _say(client, a, "다 빼줘").json()["text"] == request_flow.WHO_HOW_TEXT
    fake.data = _req("edit", target_id=sent["id"], to_ids=[ids["a"]])  # 나는 받는 사람이 될 수 없다
    assert _say(client, a, "나 넣어줘").json()["text"] == request_flow.WHO_HOW_TEXT
    fake.data = _req(
        "edit", target_id=sent["id"], to_ids=[ids["a"], "zzzz"]
    )  # 구성원이 아닌 id 는 버려진다
    assert _say(client, a, "낯선 사람 넣어줘").json()["pending_action"] is None
    fake.data = _req("edit", target_id=sent["id"], to_ids=[ids["b"]])
    assert _say(client, b, "받는 사람 바꿔줘").json()["text"] == request_flow.NOT_SENDER_EDIT
    fake.data = _req("edit", target_id="zzzz", to_ids=[ids["b"]])
    assert _say(client, a, "그 부탁 바꿔줘").json()["text"] == request_flow.NOT_FOUND_TEXT


# ---------- 취소 ----------
def test_cancel_warns_about_accepted_and_deletes_events(client, setup, fake):
    a, b, _, ids = setup
    sent = _send(client, a, [ids["b"]])
    _answer(client, b, sent["id"])
    fake.data = _req("cancel", target_id=sent["id"])
    body = _say(client, a, "장 부탁 취소해줘").json()
    assert (
        body["cards"][0]["type"] == "request_confirm"
        and body["cards"][0]["data"]["action"] == "cancel"
    )
    assert (
        "수락하신 분이 만든 일정도 같이 사라져요" in body["text"]
        and "수진이(가) 수락했어요" in body["text"]
    )
    assert len(_events(client, b)) == 1
    r = _confirm(client, a, body["pending_action"])
    assert r.status_code == 200
    assert r.json()["text"].endswith("'장 같이 봐줘' 부탁을 취소했어요.")
    assert _events(client, b) == []
    assert _requests(client, a)[0]["canceled"] is True


def test_cancel_without_accepted_cancels_immediately(client, setup, fake):
    a, b, _, ids = setup
    sent = _send(client, a, [ids["b"]])
    fake.data = _req("cancel", target_id=sent["id"])
    body = _say(client, a, "장 부탁 취소해줘").json()
    assert body["pending_action"] is None  # 아무도 수락하지 않았으면 카드 없이 바로 취소(정책 #10)
    assert body["text"].endswith("'장 같이 봐줘' 부탁을 취소했어요.")
    assert _requests(client, a)[0]["canceled"] is True


def test_receiver_cannot_cancel_via_agent(client, setup, fake):
    a, b, _, ids = setup
    sent = _send(client, a, [ids["b"]])
    fake.data = _req("cancel", target_id=sent["id"])
    assert _say(client, b, "이 부탁 취소해줘").json()["text"] == request_flow.NOT_SENDER_CANCEL


# ---------- 확인 요청은 믿지 않는다 ----------
def test_confirm_revalidates(client, setup, fake):
    a, b, _, ids = setup
    sent = _send(client, a, [ids["b"]])
    forged = {"type": "request_edit", "request_id": sent["id"], "to_ids": [ids["b"], ids["a"]]}
    assert _confirm(client, b, forged).status_code == 403  # 받는 사람은 못 바꾼다
    r = _confirm(client, a, {"type": "request_edit", "request_id": sent["id"], "to_ids": ["zzzz"]})
    assert r.status_code == 400 and r.json()["code"] == "invalid_recipients"
    r = _confirm(client, a, {"type": "request_edit", "request_id": sent["id"], "to_ids": []})
    assert r.status_code == 400 and r.json()["code"] == "invalid_action"
    assert (
        _confirm(client, b, {"type": "request_cancel", "request_id": sent["id"]}).status_code == 403
    )
    assert _confirm(client, a, {"type": "request_cancel", "request_id": ""}).status_code == 400
    draft = {"title": "", "date": "", "mode": "request", "share_ids": [ids["b"]]}
    r = _confirm(client, a, {"type": "request_register", "draft": draft})
    assert r.status_code == 400 and r.json()["code"] == "draft_incomplete"
    assert _confirm(client, a, {"type": "request_register"}).status_code == 400


# ---------- 메인 채팅 입구 ----------
def test_main_chat_entry_builds_confirmation_card_and_query_text(client, setup, fake):
    a, b, _, ids = setup
    sent = _send(client, a, [ids["b"]])
    _answer(client, b, sent["id"])
    user = _user(a, client)
    with SessionLocal() as db:
        fake.data = _req("cancel", target_id=sent["id"])
        reply = ask.ask(db, _group_id(client, a), user, "장 부탁 취소해줘")
        card = reply.confirmations[0]
        assert card["action"] == "request_cancel" and card["kind"] == "schedule"
        assert card["pending_action"]["request_id"] == sent["id"]
        assert any("장 같이 봐줘" in line for line in card["lines"])

        fake.data = _req("query", request_ids=[sent["id"]]) | {"reply": "수진이 수락했어요"}
        reply = ask.ask(db, _group_id(client, a), user, "장 부탁 어떻게 됐어?")
        assert (
            "수진이 수락했어요" in reply.answer
            and "받는 분:" in reply.answer
            and "수락" in reply.answer
        )


def _group_id(client, headers):
    return client.get("/family-group/groups/me", headers=headers).json()["id"]


def _user(headers, client):
    from app.features.family_group.models import User

    uid = client.get("/family-group/me", headers=headers).json()["id"]
    with SessionLocal() as db:
        return db.get(User, uid)


def test_query_with_empty_reply_still_answers_from_the_card(client, setup, fake):
    a, b, _, ids = setup
    sent = _send(client, a, [ids["b"]])
    fake.data = _req("query", request_ids=[sent["id"]])  # 작은 모델이 reply 를 비운 경우
    body = _say(client, a, "장 부탁 어떻게 됐어?").json()
    assert body["text"] == "'장 같이 봐줘' 부탁은 아직 수락한 분이 없어요"
    assert body["cards"][0]["type"] == "request_list"
    _answer(client, b, sent["id"])
    assert "1/1명이 수락했어요" in _say(client, a, "장 부탁 어떻게 됐어?").json()["text"]
    fake.data = _req("query", request_ids=[])  # 찾은 부탁이 없으면 기존 문구
    assert _say(client, a, "그 부탁 알려줘").json()["text"] == request_flow.NONE_FOUND_TEXT


def test_event_query_also_shows_sent_requests_like_the_briefing(client, setup, fake):
    a, b, _, ids = setup
    sent = _send(client, a, [ids["b"]])
    client.post(
        "/schedule/events",
        json={
            "title": "치과",
            "start_date": _day(),
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        },
        headers=a,
    )
    event = _events(client, a)[0]
    fake.data = {
        "intent": "query",
        "reply": "그날은 치과와 장 부탁이 있어요",
        "event_ids": [event["id"]],
        "request": _req("")["request"] | {"request_ids": [sent["id"]]},
    }
    body = _say(client, a, "그날 뭐 있어?").json()
    assert body["intent"] == "query"
    assert [c["type"] for c in body["cards"]] == ["event_list", "request_list"]
    assert body["cards"][1]["data"]["requests"][0]["id"] == sent["id"]
    assert "[부탁 목록]" in fake.calls[-1]["prompt"] and "내가 보냄" in fake.calls[-1]["prompt"]


def test_main_chat_text_lists_events_and_requests_together(client, setup, fake):
    a, b, _, ids = setup
    sent = _send(client, a, [ids["b"]])
    client.post(
        "/schedule/events",
        json={
            "title": "치과",
            "start_date": _day(),
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        },
        headers=a,
    )
    event = _events(client, a)[0]
    fake.data = {
        "intent": "query",
        "reply": "그날 일정이에요",
        "event_ids": [event["id"]],
        "request": _req("")["request"] | {"request_ids": [sent["id"]]},
    }
    with SessionLocal() as db:
        reply = ask.ask(db, _group_id(client, a), _user(a, client), "그날 뭐 있어?")
    assert "치과" in reply.answer and "장 같이 봐줘" in reply.answer and "받는 분:" in reply.answer
