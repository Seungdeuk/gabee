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


def test_missing_title_and_both_missing_texts(client, setup, fake):
    a, _, _, _ = setup
    fake.data = _register_data(date=_tomorrow())
    assert "제목" in _say(client, a, "내일 등록해줘").json()["text"]
    fake.data = _register_data()
    both = _say(client, a, "등록해줘").json()["text"]
    assert "제목" in both and "날짜" in both


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


def test_share_needs_a_confirmation_card(client, setup, fake):
    a, b, _, other = setup
    fake.data = _register_data(title="가족 모임", date=_tomorrow(), kind=1, share_ids=[other])
    body = _say(client, a, "가족 모임 내일 수진에게도 공유해서 등록해줘").json()
    assert body["cards"][0]["type"] == "register_confirm"
    assert body["cards"][0]["data"]["share"] == [{"id": other, "name": "수진"}]
    assert "수진" in body["text"] and body["pending_action"]["type"] == "register"
    assert (
        _events(client, a) == [] and _events(client, b) == []
    )  # 확인 전에는 아무것도 만들지 않는다
    calls_before = len(fake.calls)

    r = client.post("/schedule/agent/confirm", json={"action": body["pending_action"]}, headers=a)
    assert r.status_code == 200, r.text
    assert (
        r.json()["cards"][0]["type"] == "registered" and r.json()["cards"][0]["data"]["shared"] == 1
    )
    assert len(fake.calls) == calls_before  # 확인은 AI 를 부르지 않는다
    assert [e["title"] for e in _events(client, b)] == ["가족 모임"]  # 받은 사람의 복사본


def test_confirm_with_mine_only_does_not_share(client, setup, fake):
    a, b, _, other = setup
    fake.data = _register_data(title="가족 모임", date=_tomorrow(), share_ids=[other])
    action = _say(client, a, "공유해서 등록해줘").json()["pending_action"]
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
