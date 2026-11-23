"""에이전트 등록 시험. 실제 Anthropic 은 부르지 않고 llm.complete_json 을 가짜로 바꾼다(모델의 정확도가 아니라
우리 코드가 모델 출력을 어떻게 검증하고 처리하는지를 확인한다)."""

import re
from datetime import timedelta

import pytest

from app.features.schedule.agent import register
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import signup


def _register_data(**fields):
    base = {
        "title": "",
        "date": "",
        "start_time": "",
        "end_time": "",
        "kind": 0,
        "place": "",
        "memo": "",
        "share_ids": [],
        "date_ambiguous": False,
    }
    base.update(fields)
    return {"intent": "register", "reply": "", "event_ids": [], "register": base}


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.data = {}
        self.fn = None  # 프롬프트를 보고 답을 만들어야 할 때

    def __call__(self, prompt, schema, system=None, max_tokens=None, **kw):
        self.calls.append({"prompt": prompt, "system": system})
        data = self.fn(prompt) if self.fn else self.data
        return llm.JsonResult(data=data, input_tokens=100, output_tokens=20, model="fake")


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
    other = client.get("/family-group/me", headers=b).json()["id"]
    with SessionLocal() as db:
        ai_guard.set_enabled(db, group["id"], me, True)
    return a, b, me, other


def _say(client, headers, text, draft=None):
    body = {"text": text, "channel": "personal"}
    if draft is not None:
        body["draft"] = draft
    return client.post("/schedule/agent", json=body, headers=headers)


def _tomorrow() -> str:
    return (register.today() + timedelta(days=1)).isoformat()


def _events(client, headers):
    return client.get("/schedule/events", params={"include_past": True}, headers=headers).json()


def test_registers_right_away_without_asking(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="병원 예약하기", date=_tomorrow(), kind=2)
    r = _say(client, a, "내일 병원 예약하기 등록해줘")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "register" and body["text"].endswith("일정을 등록했어요.")
    assert body["draft"] is None and body["pending_action"] is None
    card = body["cards"][0]
    assert card["type"] == "registered"
    assert card["data"]["title"] == "병원 예약하기" and card["data"]["kind"] == 2
    assert card["data"]["date"] == _tomorrow() and card["data"]["start_time"] == ""
    assert len(fake.calls) == 1  # 되묻지 않고 한 번에 등록
    saved = _events(client, a)
    assert len(saved) == 1 and saved[0]["source"] == "chat" and saved[0]["kind"] == 2


def test_title_is_kept_as_said(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="엄마랑 병원", date=_tomorrow(), kind=1)
    _say(client, a, "엄마랑 병원 등록해줘 내일")
    saved = _events(client, a)[0]
    assert saved["title"] == "엄마랑 병원" and "who_ids" not in saved


def test_start_time_alone_becomes_one_hour_and_unknown_kind_is_todo(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="약속", date=_tomorrow(), start_time="14:00", kind=0)
    data = _say(client, a, "내일 오후 2시 약속").json()["cards"][0]["data"]
    assert (data["start_time"], data["end_time"]) == ("14:00", "15:00")
    assert data["kind"] == register.DEFAULT_KIND == 2


def test_missing_date_asks_and_next_answer_completes(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="병원 예약")
    first = _say(client, a, "병원 예약 등록해줘").json()
    assert first["cards"] == [] and "날짜" in first["text"]
    assert first["draft"]["title"] == "병원 예약" and first["draft"]["asks"] == 1
    assert _events(client, a) == []  # 필수가 다 모이기 전에는 저장하지 않는다
    fake.data = _register_data(title="병원 예약", date=_tomorrow())
    second = _say(client, a, "내일", draft=first["draft"]).json()
    assert second["text"].endswith("'병원 예약' 일정을 등록했어요.") and second["draft"] is None
    assert "병원 예약" in fake.calls[1]["prompt"]  # 초안이 두 번째 호출에 실려 간다
    assert len(_events(client, a)) == 1


def test_missing_title_registers_with_default_title_and_says_so(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(date=_tomorrow(), kind=1)
    body = _say(client, a, "내일 등록해줘").json()
    assert body["draft"] is None and body["cards"][0]["data"]["title"] == "약속"
    assert "제목을 말씀하지 않으셔서 '약속'으로 등록했어요." in body["text"]
    assert body["cards"][0]["data"]["title_assumed"] is True
    fake.data = _register_data(date=_tomorrow(), kind=2)
    todo = _say(client, a, "내일 뭐 좀 해야 돼 등록해줘").json()
    assert todo["cards"][0]["data"]["title"] == "할 일"
    assert "제목을 말씀하지 않으셔서 '할 일'로 등록했어요." in todo["text"]
    assert sorted(e["title"] for e in _events(client, a)) == ["약속", "할 일"]


def test_missing_title_and_date_asks_only_the_date(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data()
    body = _say(client, a, "등록해줘").json()
    assert "날짜" in body["text"] and "제목" not in body["text"]
    assert body["draft"]["asks"] == 1 and _events(client, a) == []
    # 제목 없는 초안도 날짜만 채워지면 등록한다
    fake.data = _register_data(date=_tomorrow())
    done = _say(client, a, "내일", draft=body["draft"]).json()
    assert done["cards"][0]["data"]["title"] == "할 일" and done["draft"] is None


def test_give_up_text_is_about_the_date():
    assert "날짜" in register.GIVE_UP_TEXT and "제목" not in register.GIVE_UP_TEXT


def test_title_rules_are_in_the_prompt_and_schema():
    from app.features.schedule.agent import prompts

    assert "치과 가기" in prompts.CHAT_SYSTEM and "빈 문자열" in prompts.CHAT_SYSTEM
    assert "more_registers" in prompts.CHAT_SYSTEM and "(공)" not in prompts.CHAT_SYSTEM
    for schema in (prompts.REGISTER_SCHEMA,):
        assert "time_assumed" in schema["properties"] and "time_assumed" in schema["required"]
        assert schema["additionalProperties"] is False
    assert "more_registers" in prompts.CHAT_SCHEMA["required"]
    assert prompts.CHAT_SCHEMA["properties"]["more_registers"]["items"] is prompts.REGISTER_SCHEMA


def test_cleaned_title_is_saved_as_the_model_gave_it(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="치과 가기", date=_tomorrow(), kind=1)
    body = _say(client, a, "내일 치과 가야돼").json()
    assert body["cards"][0]["data"]["title"] == "치과 가기"
    assert "title_assumed" not in body["cards"][0]["data"]
    assert [e["title"] for e in _events(client, a)] == ["치과 가기"]


def test_assumed_am_pm_is_told(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(
        title="치과", date=_tomorrow(), start_time="14:00", kind=1, time_assumed=True
    )
    body = _say(client, a, "내일 2시에 치과").json()
    assert "오후 2시로 등록했어요(오전이면 말씀해 주세요)." in body["text"]
    assert body["cards"][0]["data"]["time_assumed"] is True
    fake.data = _register_data(
        title="약국", date=_tomorrow(), start_time="09:30", time_assumed=True
    )
    assert "오전 9시 30분으로 등록했어요" in _say(client, a, "내일 9시반 약국").json()["text"]
    fake.data = _register_data(title="산책", date=_tomorrow(), start_time="15:00")  # 추정 아님
    plain = _say(client, a, "내일 오후 3시 산책").json()
    assert "오전이면" not in plain["text"] and "time_assumed" not in plain["cards"][0]["data"]


def test_time_assumed_without_a_time_is_ignored(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="치과", date=_tomorrow(), time_assumed=True)
    body = _say(client, a, "내일 저녁에 치과").json()
    assert "오전이면" not in body["text"] and body["cards"][0]["data"]["start_time"] == ""


def test_clock_text():
    assert register._clock_text("14:00") == "오후 2시"
    assert register._clock_text("12:00") == "오후 12시"
    assert register._clock_text("00:30") == "오전 12시 30분"


def _new_event(client, headers, title, start="", end="", day=None):
    body = {"title": title, "start_date": day or _tomorrow()}
    if start:
        body["start_time"] = start
    if end:
        body["end_time"] = end
    r = client.post("/schedule/events", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_overlap_is_told_but_still_registered(client, setup, fake):
    a, _, _, _ = setup
    _new_event(client, a, "치과", "15:00:00", "16:00:00")
    fake.data = _register_data(title="헬스", date=_tomorrow(), start_time="15:30", kind=1)
    body = _say(client, a, "내일 3시 반 헬스").json()
    assert "15:00 치과 일정과 시간이 겹쳐요." in body["text"]
    assert body["cards"][0]["data"]["overlaps"] == [{"title": "치과", "start_time": "15:00"}]
    assert sorted(e["title"] for e in _events(client, a)) == ["치과", "헬스"]  # 막지 않는다


def test_no_overlap_when_apart_or_without_time(client, setup, fake):
    a, _, _, _ = setup
    _new_event(client, a, "치과", "15:00:00", "16:00:00")
    _new_event(client, a, "종일 일정")  # 시간 없는 일정은 따지지 않는다
    fake.data = _register_data(title="헬스", date=_tomorrow(), start_time="16:00", kind=1)
    body = _say(client, a, "내일 4시 헬스").json()
    assert "겹쳐요" not in body["text"] and "overlaps" not in body["cards"][0]["data"]
    fake.data = _register_data(title="독서", date=_tomorrow(), kind=1)  # 새 일정에 시간이 없다
    assert "겹쳐요" not in _say(client, a, "내일 독서").json()["text"]


def test_overlap_uses_one_hour_when_end_is_missing_and_lists_at_most_three(client, setup, fake):
    a, _, _, _ = setup
    for i, name in enumerate(["가", "나", "다", "라"]):
        _new_event(client, a, name, f"1{i}:00:00")  # 끝 시간 없음 = 한 시간
    fake.data = _register_data(title="모임", date=_tomorrow(), start_time="10:00", end_time="14:30")
    data = _say(client, a, "내일 모임").json()["cards"][0]["data"]
    assert [o["title"] for o in data["overlaps"]] == ["가", "나", "다"]  # 시간순 최대 3건


def test_received_copy_counts_as_overlap(client, setup, fake):
    a, b, me, _ = setup
    body = {"title": "엄마 병원", "start_date": _tomorrow(), "start_time": "15:00:00"}
    r = client.post("/schedule/events", json={**body, "share_with": [me]}, headers=b)
    assert r.status_code == 201, r.text
    fake.data = _register_data(title="산책", date=_tomorrow(), start_time="15:30", kind=1)
    assert (
        "15:00 엄마 병원 일정과 시간이 겹쳐요." in _say(client, a, "내일 3시반 산책").json()["text"]
    )


def test_registering_twice_in_one_sentence(client, setup, fake):
    a, _, _, _ = setup
    day2 = (register.today() + timedelta(days=2)).isoformat()
    fake.data = _register_data(title="치과", date=_tomorrow(), kind=1)
    fake.data["more_registers"] = [
        {**_register_data(title="헬스", date=day2, kind=2)["register"]},
        "무시되는 항목",
    ]
    body = _say(client, a, "내일 치과 등록하고 모레 헬스 등록해줘").json()
    assert [c["data"]["title"] for c in body["cards"]] == ["치과", "헬스"]
    assert body["text"].count("일정을 등록했어요.") == 2 and body["draft"] is None
    assert sorted(e["title"] for e in _events(client, a)) == ["치과", "헬스"]
    assert len(fake.calls) == 1


def test_one_of_two_missing_a_date_asks_only_that_one(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="치과", date=_tomorrow(), kind=1)
    fake.data["more_registers"] = [_register_data(title="헬스", kind=2)["register"]]
    body = _say(client, a, "내일 치과 등록하고 헬스도 등록해줘").json()
    assert [c["data"]["title"] for c in body["cards"]] == ["치과"]
    assert body["draft"]["title"] == "헬스" and "날짜" in body["text"]
    assert [e["title"] for e in _events(client, a)] == ["치과"]
    fake.data = _register_data(title="헬스", date=_tomorrow(), kind=2)  # 답하면 그 건만 마저 등록
    done = _say(client, a, "내일", draft=body["draft"]).json()
    assert done["cards"][0]["data"]["title"] == "헬스" and done["draft"] is None


def test_second_missing_date_is_reported_not_silently_dropped(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="치과", kind=1)
    fake.data["more_registers"] = [_register_data(title="헬스", kind=2)["register"]]
    body = _say(client, a, "치과 등록하고 헬스도 등록해줘").json()
    assert body["cards"] == [] and body["draft"]["title"] == "치과"
    assert "'헬스' 일정은 날짜를 알 수 없어 등록하지 못했어요." in body["text"]


def test_more_registers_are_capped_and_cleaned():
    from app.features.schedule.agent import chat

    raw = [{"title": f"t{i}", "date": "2026-01-01", "kind": 9} for i in range(7)] + ["x", None]
    cleaned = chat.clean_more(raw, set())
    assert len(cleaned) == chat.MAX_MORE_REGISTERS == 4 and cleaned[0]["kind"] == 0
    assert chat.clean_more("bad", set()) == []


def test_delete_request_misclassified_as_query_becomes_a_delete_card(client, setup, fake):
    a, _, _, _ = setup
    old = _new_event(client, a, "헬스")
    fake.data = {
        "intent": "query",
        "reply": "헬스 일정이 있어요",
        "event_ids": [old["id"]],
        "register": _register_data()["register"],
        "request": {"request_ids": []},
    }
    body = _say(client, a, "헬스 다 지워줘").json()
    assert body["pending_action"]["type"] == "delete"
    assert body["cards"][0]["type"] == "delete_confirm"
    assert [e["title"] for e in _events(client, a)] == ["헬스"]  # 확인 전에는 지우지 않는다
    done = client.post(
        "/schedule/agent/confirm", json={"action": body["pending_action"]}, headers=a
    ).json()
    assert _events(client, a) == [] and done["intent"] == "delete"


def test_asking_about_an_event_stays_a_query(client, setup, fake):
    a, _, _, _ = setup
    old = _new_event(client, a, "헬스")
    fake.data = {
        "intent": "query",
        "reply": "헬스 일정이 있어요",
        "event_ids": [old["id"]],
        "register": _register_data()["register"],
        "request": {"request_ids": []},
    }
    body = _say(client, a, "헬스 지워줘도 돼? 알려줘").json()
    assert body["intent"] == "query" and body["pending_action"] is None


def test_private_register_clears_share_ids(client, family, fake):
    a, b, group = family
    me = client.get("/family-group/me", headers=a).json()["id"]
    other = client.get("/family-group/me", headers=b).json()["id"]
    from app.features.schedule.agent import members as members_mod

    with SessionLocal() as db:
        members = members_mod.load(db, group["id"])
        fields = register.clean_fields(
            _register_data(title="치과", date=_tomorrow(), kind=1, share_ids=[other])["register"],
            {m.id for m in members},
        )
        resp = register.respond(db, me, group["id"], None, fields, "", members, False, "", True)
    assert resp.cards[0].data["shared"] == 0
    assert [e["title"] for e in _events(client, b)] == []


def test_ambiguous_date_uses_model_question(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="치과", date_ambiguous=True)
    fake.data["reply"] = "이번 주 금요일인가요, 다음 주 금요일인가요?"
    body = _say(client, a, "금요일에 치과 등록해줘").json()
    assert body["text"] == "이번 주 금요일인가요, 다음 주 금요일인가요?"
    assert body["draft"]["date"] == "" and _events(client, a) == []


def test_gives_up_after_two_questions(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="병원")
    draft = {"title": "병원", "asks": register.MAX_ASKS}
    body = _say(client, a, "음 글쎄", draft=draft).json()
    assert body["text"] == register.GIVE_UP_TEXT and body["draft"] is None


def test_model_output_is_validated(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="치과", date="2026-13-45")  # 없는 날짜는 비어 있는 것으로
    assert _say(client, a, "치과 등록해줘").json()["draft"]["date"] == ""
    far = (register.today() + timedelta(days=5000)).isoformat()
    fake.data = _register_data(title="치과", date=far, kind=7, share_ids=["zzz"])  # 범위 밖 날짜
    assert _say(client, a, "치과 먼 훗날 등록해줘").json()["cards"] == []
    fake.data = _register_data(title="치과", date=_tomorrow(), kind=7, share_ids=["zzz"])
    body = _say(client, a, "치과 내일 등록해줘").json()
    assert body["pending_action"] is None  # 구성원이 아닌 공유 대상은 없는 것
    assert body["cards"][0]["data"]["kind"] == 2


def test_share_registers_immediately_without_a_card(client, setup, fake):
    a, b, _, other = setup
    fake.data = _register_data(title="가족 모임", date=_tomorrow(), kind=1, share_ids=[other])
    body = _say(client, a, "가족 모임 내일 수진에게도 공유해서 등록해줘").json()
    # 정책 #32: 공유 등록도 확인 카드 없이 바로 등록하고 누구에게 공유했는지 안내한다
    assert body["pending_action"] is None
    assert body["cards"][0]["type"] == "registered" and body["cards"][0]["data"]["shared"] == 1
    assert "수진" in body["text"] and "공유해서 등록했어요" in body["text"]
    assert [e["title"] for e in _events(client, a)] == ["가족 모임"]
    assert [e["title"] for e in _events(client, b)] == ["가족 모임"]  # 받은 사람의 복사본


def test_confirm_with_mine_only_does_not_share(client, setup, fake):
    a, b, _, other = setup
    # 예전 앱이 보낸 확인 요청도 계속 받는다(공유 없이 내 일정만 등록)
    action = {
        "type": "register",
        "draft": {"title": "가족 모임", "date": _tomorrow(), "share_ids": [other]},
    }
    r = client.post("/schedule/agent/confirm", json={"action": action, "share": False}, headers=a)
    assert r.status_code == 200 and r.json()["cards"][0]["data"]["shared"] == 0
    assert len(_events(client, a)) == 1 and _events(client, b) == []


def test_confirm_does_not_trust_the_returned_draft(client, setup, fake):
    a, b, me, other = setup
    outsider = signup(client, "남")
    group = client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider).json()
    outsider_id = client.get("/family-group/me", headers=outsider).json()["id"]
    draft = {"title": "몰래", "date": _tomorrow(), "share_ids": [outsider_id, me, other]}
    r = client.post(
        "/schedule/agent/confirm", json={"action": {"type": "register", "draft": draft}}, headers=a
    )
    assert r.status_code == 200, r.text
    assert (
        r.json()["cards"][0]["data"]["shared"] == 1
    )  # 다른 가족 사람과 나는 빠지고 구성원만 남는다
    assert _events(client, outsider) == [] and group["id"]
    bad = {"type": "register", "draft": {"title": "", "date": ""}}
    r = client.post("/schedule/agent/confirm", json={"action": bad}, headers=a)
    assert r.status_code == 400 and r.json()["code"] == "draft_incomplete"
    r = client.post(
        "/schedule/agent/confirm", json={"action": {"type": "register"}}, headers=a
    )  # 등록 확인인데 초안이 없다
    assert r.status_code == 400 and r.json()["code"] == "invalid_action"
    r = client.post(
        "/schedule/agent/confirm", json={"action": {"type": "delete", "event_id": "x"}}, headers=a
    )  # 삭제 확인은 이제 처리하며, 없는 일정은 404
    assert r.status_code == 404


def test_personal_info_is_masked_out_and_restored_on_save(client, setup, fake):
    a, _, _, _ = setup

    def answer(prompt):
        token = re.search(r"\[PHONE_\d+\]", prompt).group(0)  # 모델은 가려진 자리표시자만 본다
        return _register_data(title=f"예약 확인 {token}", date=_tomorrow(), kind=2)

    fake.fn = answer
    r = _say(client, a, "예약 확인 010-1234-5678 내일 등록해줘")
    assert r.status_code == 200, r.text
    assert "1234-5678" not in fake.calls[0]["prompt"]
    assert r.json()["cards"][0]["data"]["title"] == "예약 확인 010-1234-5678"
    assert _events(client, a)[0]["title"] == "예약 확인 010-1234-5678"  # 저장된 값은 원래 값


def test_sensitive_content_is_not_sent_or_registered(client, setup, fake):
    a, _, _, _ = setup
    r = _say(client, a, "주민번호 900101-1234568 병원 내일 등록해줘")
    assert r.status_code == 400 and r.json()["code"] == "sensitive_content"
    assert fake.calls == [] and _events(client, a) == []


def test_register_needs_ai_consent_but_confirm_does_not(client, family, fake):
    a, _, _ = family
    fake.data = _register_data(title="치과", date=_tomorrow())
    assert _say(client, a, "치과 등록해줘").json()["code"] == "ai_not_enabled"
    draft = {"title": "치과", "date": _tomorrow()}
    r = client.post(
        "/schedule/agent/confirm", json={"action": {"type": "register", "draft": draft}}, headers=a
    )
    assert r.status_code == 200  # AI 를 부르지 않는 확인 단계는 동의와 상관없다


def test_ambiguous_member_asks_who_before_registering(client, setup, fake):
    a, b, _, other = setup
    data = _register_data(title="가족 모임", date=_tomorrow(), member_ambiguous=True)
    data["reply"] = "삼촌이 두 분이에요. 누구를 말씀하시나요? (수진, 지훈)"
    fake.data = data
    body = _say(client, a, "삼촌한테 공유해서 가족 모임 내일 등록해줘").json()
    # 제목·날짜가 다 있어도 같은 호칭의 가족이 여럿이면 등록하지 않고 후보를 보여 주며 되묻는다(정책 #33)
    assert body["text"] == data["reply"] and body["pending_action"] is None
    assert body["draft"]["title"] == "가족 모임" and body["cards"] == []
    assert _events(client, a) == [] and _events(client, b) == []

    fake.data = _register_data(
        share_ids=[other]
    )  # 사용자가 "수진"이라고 답하면 초안과 합쳐 등록한다
    done = _say(client, a, "수진", draft=body["draft"]).json()
    assert done["cards"][0]["type"] == "registered" and "수진" in done["text"]
    assert [e["title"] for e in _events(client, b)] == ["가족 모임"]


def test_register_with_a_delete_in_the_same_sentence_does_each_by_its_own_policy(
    client, setup, fake
):
    a, _, _, _ = setup
    old = client.post(
        "/schedule/events", json={"title": "헬스", "start_date": _tomorrow()}, headers=a
    ).json()
    data = _register_data(title="치과", date=_tomorrow())
    data["also_delete_title"] = "헬스"  # 목록에 없어도 제목으로 전체에서 찾는다
    fake.data = data
    body = _say(client, a, "치과 내일 등록하고 헬스는 지워줘").json()
    # 등록은 바로 하고, 삭제는 확인 카드로 묻는다(정책 #34). 삭제 지시를 조용히 버리지 않는다
    assert [c["type"] for c in body["cards"]] == ["registered", "delete_confirm"]
    assert "등록했어요" in body["text"] and "지울까요" in body["text"]
    assert (
        body["pending_action"]["type"] == "delete"
        and body["pending_action"]["event_id"] == old["id"]
    )
    assert sorted(e["title"] for e in _events(client, a)) == ["치과", "헬스"]  # 삭제는 확인 전
    done = client.post(
        "/schedule/agent/confirm", json={"action": body["pending_action"]}, headers=a
    ).json()
    assert "지웠어요" in done["text"] and [e["title"] for e in _events(client, a)] == ["치과"]


def test_registering_an_existing_event_asks_before_registering_again(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="치과", date=_tomorrow(), start_time="15:00", kind=1)
    _say(client, a, "내일 3시 치과 등록해줘")
    body = _say(client, a, "내일 3시 치과 등록해줘").json()
    assert "이미 등록되어 있어요. 또 등록해 드릴까요?" in body["text"]
    assert len(_events(client, a)) == 1  # 묻기만 하고 아직 만들지 않는다
    done = _say(client, a, "응").json()  # AI 를 다시 부르지 않고 그대로 또 등록한다
    assert done["cards"][0]["type"] == "registered" and len(_events(client, a)) == 2


def test_no_to_registering_again_keeps_one_event(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(title="치과", date=_tomorrow(), start_time="15:00", kind=1)
    _say(client, a, "내일 3시 치과 등록해줘")
    _say(client, a, "내일 3시 치과 등록해줘")
    body = _say(client, a, "아니").json()
    assert "다시 등록하지 않았어요" in body["text"] and len(_events(client, a)) == 1


def test_registering_with_a_shorter_title_matches_the_existing_event_by_keywords(
    client, setup, fake
):
    a, _, _, _ = setup
    fake.data = _register_data(title="하윤 치과 검진", date=_tomorrow(), start_time="15:30", kind=1)
    _say(client, a, "내일 3시반 하윤 치과 검진 등록해줘")
    fake.data = _register_data(title="치과 하윤", date=_tomorrow(), start_time="", kind=1)
    body = _say(client, a, "내일 하윤 치과 등록해줘").json()
    assert "이미 등록되어 있어요. 또 등록해 드릴까요?" in body["text"]
    assert len(_events(client, a)) == 1
