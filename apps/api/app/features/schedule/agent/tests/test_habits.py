"""데일리 체크 연결 시험. 실제 Anthropic 은 부르지 않고 llm.complete_json 을 가짜로 바꾼다(모델의 정확도가 아니라
우리 코드가 모델 출력을 어떻게 검증하고 조회·확인 카드·기록으로 처리하는지를 확인한다)."""

import pytest

from app.features.schedule.agent import habits
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.llm import client as llm


def _data(action, *ids, amount=1):
    return {
        "intent": "habit",
        "reply": "",
        "event_ids": [],
        "habit": {"action": action, "item_ids": list(ids), "amount": amount},
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


def _habit(client, headers, name, **fields) -> dict:
    r = client.post("/schedule/check/items", json={"name": name, **fields}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _say(client, headers, text, channel="personal"):
    return client.post(
        "/schedule/agent", json={"text": text, "channel": channel}, headers=headers
    ).json()


def _confirm(client, headers, pending):
    return client.post("/schedule/agent/confirm", json={"action": pending}, headers=headers)


def _today(client, headers) -> dict:
    items = client.get("/schedule/check/items", headers=headers).json()
    return {i["name"]: i for i in items}


def test_list_reads_the_state_from_the_database(client, setup, fake):
    a, _ = setup
    pill = _habit(client, a, "약 먹기")
    water = _habit(client, a, "물 마시기", kind=2, goal=8, unit="잔")
    client.put(f"/schedule/check/items/{pill['id']}/entry", json={"done": True}, headers=a)
    client.put(f"/schedule/check/items/{water['id']}/entry", json={"count": 3}, headers=a)
    fake.data = _data("list", pill["id"], water["id"], "zzz")  # 목록에 없는 id 는 버려진다
    body = _say(client, a, "오늘 습관 어때?")
    assert body["intent"] == "habit" and body["pending_action"] is None
    assert "약 먹기: 완료" in body["text"] and "물 마시기: 3/8잔" in body["text"]
    assert "약 먹기" in fake.calls[0]["prompt"] and "[데일리 체크]" in fake.calls[0]["prompt"]


def test_mark_asks_for_a_card_and_records_only_after_confirm(client, setup, fake):
    a, _ = setup
    pill = _habit(client, a, "약 먹기")
    fake.data = _data("mark", pill["id"])
    body = _say(client, a, "약 먹었어")
    pending = body["pending_action"]
    assert pending["type"] == "habit_check" and pending["habit_ids"] == [pill["id"]]
    assert body["cards"][0]["type"] == "habit_confirm"
    assert _today(client, a)["약 먹기"]["done"] is False  # 카드를 누르기 전에는 기록하지 않는다
    done = _confirm(client, a, pending)
    assert done.status_code == 200, done.text
    assert "체크했어요" in done.json()["text"]
    assert _today(client, a)["약 먹기"]["done"] is True


def test_count_habit_adds_the_amount_and_unmark_subtracts(client, setup, fake):
    a, _ = setup
    water = _habit(client, a, "물 마시기", kind=2, goal=8, unit="잔")
    fake.data = _data("mark", water["id"], amount=2)
    pending = _say(client, a, "물 두 잔 마셨어")["pending_action"]
    _confirm(client, a, pending)
    assert _today(client, a)["물 마시기"]["count"] == 2
    fake.data = _data("unmark", water["id"], amount=1)
    _confirm(client, a, _say(client, a, "한 잔은 취소")["pending_action"])
    assert _today(client, a)["물 마시기"]["count"] == 1


def test_already_checked_needs_no_card(client, setup, fake):
    a, _ = setup
    pill = _habit(client, a, "약 먹기")
    client.put(f"/schedule/check/items/{pill['id']}/entry", json={"done": True}, headers=a)
    fake.data = _data("mark", pill["id"])
    body = _say(client, a, "약 먹었어")
    assert body["pending_action"] is None and "이미" in body["text"]


def test_family_room_reads_only_shared_habits(client, setup, fake):
    a, _ = setup
    _habit(client, a, "비밀 습관", shared=False)
    shown = _habit(client, a, "산책", shared=True)
    fake.data = _data("list")
    body = _say(client, a, "오늘 습관", channel="family")
    prompt = fake.calls[0]["prompt"]
    assert "산책" in prompt and "비밀 습관" not in prompt
    assert "산책" in body["text"] and "비밀 습관" not in body["text"]
    # 개인 채팅에서는 둘 다 읽는다
    _say(client, a, "오늘 습관")
    assert "비밀 습관" in fake.calls[1]["prompt"] and shown["id"] in fake.calls[1]["prompt"]


def test_other_members_shared_habit_is_readable_but_not_checkable(client, setup, fake):
    a, b = setup
    theirs = _habit(client, b, "안부 전화", shared=True)
    _habit(client, b, "일기", shared=False)
    fake.data = _data("list", theirs["id"])
    assert "안부 전화: 아직" in _say(client, a, "가족 습관 알려줘")["text"]
    assert (
        "일기" not in fake.calls[0]["prompt"]
    )  # 가족에게 보이지 않는 습관은 모델에도 보내지 않는다
    fake.data = _data("mark", theirs["id"])
    body = _say(client, a, "안부 전화 했어")
    assert body["text"] == habits.NOT_MINE_TEXT and body["pending_action"] is None
    assert _today(client, b)["안부 전화"]["done"] is False


def test_confirm_ignores_someone_elses_habit_id(client, setup, fake):
    a, b = setup
    theirs = _habit(client, b, "안부 전화", shared=True)
    forged = {"type": "habit_check", "habit_ids": [theirs["id"]], "habit_op": "mark", "amount": 1}
    res = _confirm(client, a, forged)
    assert "찾지 못했어요" in res.json()["text"]
    assert _today(client, b)["안부 전화"]["done"] is False


def test_unknown_target_and_bad_action(client, setup, fake):
    a, _ = setup
    _habit(client, a, "약 먹기")
    fake.data = _data("mark", "zzz")
    body = _say(client, a, "운동했어")
    assert body["text"] == habits.NOT_FOUND_TEXT and body["pending_action"] is None
    fake.data = _data("delete", "zzz", amount=999)  # 보기 밖 action·범위 밖 amount
    cleaned = habits.clean_fields({"action": "delete", "item_ids": ["x"], "amount": 999}, {"x"})
    assert cleaned == {"action": "", "item_ids": ["x"], "amount": 100}


def test_no_habits_says_so(client, setup, fake):
    a, _ = setup
    fake.data = _data("list")
    assert _say(client, a, "오늘 습관 어때?")["text"] == habits.NONE_TEXT
