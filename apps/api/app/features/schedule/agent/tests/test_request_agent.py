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
def test_create_asks_confirm_then_sends(client, setup, fake):
    a, b, _, ids = setup
    fake.data = _req(
        "create", title="병원 같이 가요", date=_day(), start_time="10:00", to_ids=[ids["b"]]
    )
    body = _say(client, a, "수진한테 병원 같이 가달라고 부탁해줘").json()
    assert body["text"].endswith("에게 부탁을 보낼까요?")
    assert body["cards"][0]["type"] == "request_confirm"
    assert body["cards"][0]["data"]["to"][0]["id"] == ids["b"]
    action = body["pending_action"]
    assert action["type"] == "request_register" and action["draft"]["mode"] == "request"
    assert _requests(client, b) == []  # 확인 전에는 보내지 않는다
    calls = len(fake.calls)

    r = _confirm(client, a, action)
    assert r.status_code == 200, r.text
    # 승인 뒤의 안내는 #466 이 넣은 대로 어떤 부탁을 누구에게 보냈는지 말해 준다(문장만 달라졌고 승인 순서는 그대로)
    assert "'병원 같이 가요' 부탁을 수진에게 보냈어요." in r.json()["text"]
    assert len(fake.calls) == calls  # 확인은 AI 를 부르지 않는다
    got = _requests(client, b)
    assert [x["title"] for x in got] == ["병원 같이 가요"] and got[0]["start_time"] == "10:00:00"
    assert got[0]["end_time"] == "11:00:00"  # 시작만 말하면 한 시간 뒤


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
    assert body["cards"][0]["type"] == "request_confirm"
    assert body["pending_action"]["draft"]["title"] == "장 봐줘"
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
def test_edit_adds_and_removes_recipients(client, setup, fake):
    a, b, c, ids = setup
    sent = _send(client, a, [ids["b"]])
    fake.data = _req("edit", target_id=sent["id"], to_ids=[ids["b"], ids["c"]])
    body = _say(client, a, "장 부탁에 민수도 넣어줘").json()
    assert body["text"] == "이렇게 바꿀까요?"
    change = body["cards"][0]["data"]["changes"][0]
    assert (
        change["label"] == "받는 사람"
        and "민수" in change["after"]
        and "민수" not in change["before"]
    )
    assert _requests(client, c) == []
    assert _confirm(client, a, body["pending_action"]).status_code == 200
    assert len(_requests(client, c)) == 1

    fake.data = _req("edit", target_id=sent["id"], to_ids=[ids["c"]])
    body = _say(client, a, "수진은 빼줘").json()
    assert "수락한 분" not in body["text"]  # 수락 전이라 일정 삭제 안내는 없다
    assert _confirm(client, a, body["pending_action"]).status_code == 200
    assert _requests(client, b) == []


def test_edit_removing_accepted_warns_and_deletes_their_event(client, setup, fake):
    a, b, c, ids = setup
    sent = _send(client, a, [ids["b"], ids["c"]])
    _answer(client, b, sent["id"])
    assert len(_events(client, b)) == 1
    fake.data = _req("edit", target_id=sent["id"], to_ids=[ids["c"]])
    body = _say(client, a, "수진 빼줘").json()
    assert "수락한 분을 제외하면 그 일정도 같이 사라져요" in body["text"]
    assert len(_events(client, b)) == 1  # 확인 전에는 지우지 않는다
    assert _confirm(client, a, body["pending_action"]).status_code == 200
    assert _events(client, b) == []


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
    assert "수락하신 분이 만든 일정도 같이 사라져요" in body["text"]
    assert len(_events(client, b)) == 1
    r = _confirm(client, a, body["pending_action"])
    assert r.status_code == 200
    assert r.json()["text"].endswith(
        "'장 같이 봐줘' 부탁을 취소했어요."
    )  # 어떤 부탁인지 말해 준다(#466)
    assert _events(client, b) == []
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


def test_create_with_ambiguous_member_asks_who_and_sends_nothing(client, setup, fake):
    a, b, _, ids = setup
    data = _req("create", title="병원 같이 가요", date=_day(), member_ambiguous=True)
    data["reply"] = "삼촌이 두 분이에요. 누구를 말씀하시나요? (수진, 지훈)"
    fake.data = data
    body = _say(client, a, "삼촌한테 병원 같이 가달라고 부탁해줘").json()
    assert body["text"] == data["reply"] and body["pending_action"] is None
    assert body["draft"]["mode"] == "request" and _requests(client, b) == []


# ---------- 승인 전 DB 변경 0건·메모는 채팅에서 쓰지 않는다 ----------
def _snap_requests(client, setup):
    a, b, c, _ = setup
    return [_requests(client, h) for h in (a, b, c)], [_events(client, h) for h in (a, b, c)]


def test_request_writes_never_happen_before_the_user_approves(client, setup, fake):
    """보내기·받는 사람 바꾸기·취소는 상대에게 영향이 가므로 카드가 나온 시점의 DB 는 그대로다(수락한 사람이 없어도 취소는 카드)."""
    a, b, c, ids = setup
    sent = _send(client, a, [ids["b"]])
    before = _snap_requests(client, setup)

    fake.data = _req("create", title="병원", date=_day(), to_ids=[ids["c"]])
    body = _say(client, a, "민수한테 병원 부탁해줘").json()
    assert (
        body["pending_action"]["type"] == "request_register"
        and body["cards"][0]["type"] == "request_confirm"
    )
    assert "보냈어요" not in body["text"]
    assert _snap_requests(client, setup) == before

    fake.data = _req("edit", target_id=sent["id"], to_ids=[ids["b"], ids["c"]])
    body = _say(client, a, "장 부탁에 민수도 넣어줘").json()
    assert (
        body["pending_action"]["type"] == "request_edit"
        and body["cards"][0]["type"] == "request_confirm"
    )
    assert _snap_requests(client, setup) == before

    fake.data = _req("cancel", target_id=sent["id"])  # 아무도 수락하지 않아도 카드를 거친다
    body = _say(client, a, "장 부탁 취소해줘").json()
    assert (
        body["pending_action"]["type"] == "request_cancel"
        and body["cards"][0]["type"] == "request_confirm"
    )
    assert "취소했어요" not in body["text"]
    assert _snap_requests(client, setup) == before

    assert (
        _confirm(client, a, body["pending_action"]).status_code == 200
    )  # 승인하면 그 부탁만 취소된다
    assert _requests(client, a)[0]["canceled"] is True


def test_chat_never_writes_a_request_memo(client, setup, fake):
    """부탁 메모는 사용자가 앱 상세 화면에서 직접 바꾼다(`PUT /schedule/requests/{id}/memo`). 채팅은 DB 를 바꾸지 않고 안내만 한다."""
    a, b, c, ids = setup
    sent = _send(client, a, [ids["b"]], memo="처음 메모")
    before = _snap_requests(client, setup)
    fake.data = _req("edit", target_id=sent["id"], memo="바뀐 메모")
    body = _say(client, a, "장 부탁 메모를 바꿔줘").json()
    assert body["text"] == request_flow.MEMO_IN_APP_TEXT and body["pending_action"] is None
    assert _snap_requests(client, setup) == before
    # 받는 사람 변경과 함께 말해도 메모는 쓰지 않고 받는 사람 변경만 카드로 묻는다
    fake.data = _req("edit", target_id=sent["id"], memo="바뀐 메모", to_ids=[ids["b"], ids["c"]])
    body = _say(client, a, "메모 바꾸고 민수도 넣어줘").json()
    assert (
        body["pending_action"]["type"] == "request_edit"
        and "메모는 채팅에서 바꾸지 않아요" in body["text"]
    )
    assert _snap_requests(client, setup) == before
    assert _requests(client, a)[0]["memo"] == "처음 메모"
    # 앱에서 사용자가 직접 바꾸는 경로는 그대로다
    r = client.put(f"/schedule/requests/{sent['id']}/memo", json={"memo": "앱에서 바꿈"}, headers=a)
    assert r.status_code == 200, r.text
    assert _requests(client, a)[0]["memo"] == "앱에서 바꿈"


def test_create_puts_extra_explanation_in_memo_field_after_approval(client, setup, fake):
    a, b, c, ids = setup
    fake.data = _req(
        "create", title="마트 장보기", date=_day(), memo="우유랑 계란", to_ids=[ids["b"]]
    )
    body = _say(client, a, "수진한테 마트 가서 우유랑 계란 사다 달라고 부탁해줘").json()
    assert _requests(client, b) == [] and body["cards"][0]["data"]["memo"] == "우유랑 계란"
    assert "memo(제목으로 정리한 말 밖의 부연설명" in fake.calls[-1]["system"]  # 프롬프트 규칙
    assert _confirm(client, a, body["pending_action"]).status_code == 200
    assert _requests(client, b)[0]["memo"] == "우유랑 계란"


# ---------- 같은 제목의 부탁이 여럿일 때(정책 #33) ----------
def test_same_title_requests_ask_which_then_cancel_card_for_the_chosen_one(client, setup, fake):
    a, b, _, ids = setup
    first = _send(client, a, [ids["b"]], start_date=_day(3))
    second = _send(client, a, [ids["b"]], start_date=_day(10))
    fake.data = _req("cancel", target_id=first["id"])
    body = _say(client, a, "장 부탁 취소해줘").json()
    assert "어느 쪽인가요? 모두인가요?" in body["text"] and body["pending_action"] is None
    assert [r["id"] for r in body["cards"][0]["data"]["requests"]] == [first["id"], second["id"]]
    assert not any(r["canceled"] for r in _requests(client, a))

    day = _day(10)
    card = _say(client, a, f"{int(day[5:7])}/{int(day[8:10])} 걸로").json()
    assert card["pending_action"]["request_id"] == second["id"]  # 취소도 확인 카드를 거친다
    assert not any(r["canceled"] for r in _requests(client, a))
    assert _confirm(client, a, card["pending_action"]).status_code == 200
    canceled = {r["id"]: r["canceled"] for r in _requests(client, a)}
    assert canceled[second["id"]] is True and canceled[first["id"]] is False


def test_same_title_requests_all_answer_asks_one_at_a_time_and_past_plus_future_uses_future(
    client, setup, fake
):
    a, b, _, ids = setup
    first = _send(client, a, [ids["b"]], start_date=_day(3))
    _send(client, a, [ids["b"]], start_date=_day(10))
    fake.data = _req("cancel", target_id=first["id"])
    _say(client, a, "장 부탁 취소해줘")
    body = _say(client, a, "둘 다 취소해줘").json()
    assert "한 번에 한 건씩" in body["text"] and body["pending_action"] is None
    assert not any(r["canceled"] for r in _requests(client, a))

    past = _send(client, a, [ids["b"]], title="청소", start_date=_day(-3))
    future = _send(client, a, [ids["b"]], title="청소", start_date=_day(6))
    fake.data = _req("cancel", target_id=past["id"])  # 지난 부탁을 골라도 다가오는 하나만 카드로 묻는다
    body = _say(client, a, "청소 부탁 취소해줘").json()
    assert body["pending_action"]["request_id"] == future["id"]
