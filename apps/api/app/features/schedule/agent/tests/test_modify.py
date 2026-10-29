"""에이전트 수정·삭제 시험. 실제 Anthropic 은 부르지 않고 llm.complete_json 을 가짜로 바꾼다(모델의 정확도가 아니라
우리 코드가 모델 출력을 어떻게 검증하고 확인 카드·실행으로 처리하는지를 확인한다)."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.features.schedule.agent import modify, register
from app.features.schedule.models import Event
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.llm import client as llm


def _data(intent, target="", **changes):
    base = {
        "title": "",
        "date": "",
        "start_time": "",
        "end_time": "",
        "kind": 0,
        "place": "",
        "memo": "",
        "clear": [],
        "share_change": False,
        "share_ids": [],
    }
    base.update(changes)
    return {"intent": intent, "reply": "", "event_ids": [], "target_id": target, "changes": base}


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.data = {}
        self.fn = None

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
    return a, b, me, other, group["id"]


def _day(n: int = 2) -> str:
    return (register.today() + timedelta(days=n)).isoformat()


def _new(client, headers, title="치과", **fields):
    body = {
        "title": title,
        "start_date": _day(),
        "start_time": "14:00:00",
        "end_time": "15:00:00",
        **fields,
    }
    r = client.post("/schedule/events", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _say(client, headers, text):
    return client.post(
        "/schedule/agent", json={"text": text, "channel": "personal"}, headers=headers
    )


def _confirm(client, headers, action):
    return client.post("/schedule/agent/confirm", json={"action": action}, headers=headers)


def _events(client, headers):
    return client.get("/schedule/events", params={"include_past": True}, headers=headers).json()


# ---------- 삭제 ----------
def test_delete_asks_first_and_runs_on_confirm(client, setup, fake):
    a, _, _, _, _ = setup
    e = _new(client, a)
    fake.data = _data("delete", e["id"])
    body = _say(client, a, "치과 지워줘").json()
    assert body["intent"] == "delete" and "치과" in body["text"]
    assert body["cards"][0]["type"] == "delete_confirm"
    assert body["cards"][0]["data"]["event"]["title"] == "치과"
    assert body["pending_action"] == {
        "type": "delete",
        "event_id": e["id"],
        "changes": {},
        "draft": None,
    }
    assert len(_events(client, a)) == 1  # 확인 전에는 지우지 않는다
    calls = len(fake.calls)

    r = _confirm(client, a, body["pending_action"])
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "지웠어요." and r.json()["intent"] == "delete"
    assert _events(client, a) == []
    assert len(fake.calls) == calls  # 확인은 AI 를 부르지 않는다
    with SessionLocal() as db:
        assert db.get(Event, e["id"]).deleted_at is not None  # 지우지 않고 삭제 시각만 남는다


def test_delete_leaves_shared_copies(client, setup, fake):
    a, b, _, other, _ = setup
    e = _new(client, a, share_with=[other])
    fake.data = _data("delete", e["id"])
    action = _say(client, a, "치과 지워줘").json()["pending_action"]
    assert _confirm(client, a, action).status_code == 200
    assert _events(client, a) == []
    assert [x["title"] for x in _events(client, b)] == ["치과"]  # 복사본은 받은 사람의 일정


def test_unknown_target_is_not_acted_on(client, setup, fake):
    a, _, _, _, _ = setup
    _new(client, a)
    fake.data = _data("delete", "zzzz")  # 보여 준 목록에 없는 id 는 버려진다
    body = _say(client, a, "치과 지워줘").json()
    assert body["text"] == modify.NOT_FOUND_TEXT
    assert body["pending_action"] is None and body["cards"] == []
    fake.data = _data("edit", "", title="새 제목")
    body = _say(client, a, "치과 이름 바꿔줘").json()
    assert body["text"] == modify.NOT_FOUND_TEXT and body["pending_action"] is None


def test_cannot_delete_or_edit_someone_elses_ownerless_event(client, setup, fake):
    a, _, me, other, group_id = setup
    with SessionLocal() as db:  # 주인이 없는 옛 일정은 그룹이 보지만 만든 사람만 고치고 지운다
        db.add(
            Event(
                id="old3",
                group_id=group_id,
                title="옛 일정",
                starts_at=datetime.now(UTC) + timedelta(days=2),
                created_by=other,
            )
        )
        db.commit()
    fake.data = _data("delete", "old3")
    assert _say(client, a, "옛 일정 지워줘").json()["text"] == modify.NOT_OWNER_DELETE
    fake.data = _data("edit", "old3", title="가로채기")
    assert _say(client, a, "옛 일정 이름 바꿔줘").json()["text"] == modify.NOT_OWNER_EDIT


# ---------- 수정 ----------
def test_edit_shows_before_and_after_then_applies(client, setup, fake):
    a, _, _, _, _ = setup
    e = _new(client, a, place="강남")
    fake.data = _data("edit", e["id"], start_time="16:00", place="서초")
    body = _say(client, a, "치과 4시로 장소는 서초로 바꿔줘").json()
    assert body["intent"] == "edit" and body["text"] == "이렇게 바꿀까요?"
    card = body["cards"][0]
    assert card["type"] == "edit_confirm" and card["data"]["event"]["title"] == "치과"
    by_label = {c["label"]: c for c in card["data"]["changes"]}
    assert by_label["시간"] == {"label": "시간", "before": "14:00~15:00", "after": "16:00~17:00"}
    assert by_label["장소"] == {"label": "장소", "before": "강남", "after": "서초"}
    assert "날짜" not in by_label  # 바뀌지 않는 항목은 보이지 않는다
    assert body["pending_action"]["changes"] == {
        "start_time": "16:00",
        "end_time": "17:00",  # 시작만 말하면 원래 길이(1시간)를 유지한다
        "place": "서초",
    }
    assert _events(client, a)[0]["start_time"] == "14:00:00"  # 확인 전에는 바꾸지 않는다

    r = _confirm(client, a, body["pending_action"])
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "바꿨어요."
    saved = _events(client, a)[0]
    assert (saved["start_time"], saved["end_time"], saved["place"]) == (
        "16:00:00",
        "17:00:00",
        "서초",
    )
    assert saved["edited_at"] is not None


def test_edit_title_date_and_clear_time(client, setup, fake):
    a, _, _, _, _ = setup
    e = _new(client, a)
    fake.data = _data("edit", e["id"], title="치과 검진", date=_day(5), clear=["time", "bogus"])
    body = _say(client, a, "치과 이름과 날짜 바꾸고 시간은 없애줘").json()
    by_label = {c["label"]: c for c in body["cards"][0]["data"]["changes"]}
    assert by_label["제목"]["after"] == "치과 검진"
    assert by_label["시간"] == {"label": "시간", "before": "14:00~15:00", "after": "시간 없음"}
    assert by_label["날짜"]["before"] != by_label["날짜"]["after"]
    assert _confirm(client, a, body["pending_action"]).status_code == 200
    saved = _events(client, a)[0]
    assert saved["title"] == "치과 검진" and saved["start_date"] == _day(5)
    assert saved["start_time"] is None and saved["end_time"] is None


def test_edit_with_nothing_to_change_or_bad_time(client, setup, fake):
    a, _, _, _, _ = setup
    e = _new(client, a)
    fake.data = _data("edit", e["id"])  # 바꿀 값이 없다
    assert _say(client, a, "치과 바꿔줘").json()["text"] == modify.NOTHING_TEXT
    fake.data = _data("edit", e["id"], title="치과")  # 지금과 같은 값
    assert _say(client, a, "치과 이름 치과로").json()["text"] == modify.NOTHING_TEXT
    fake.data = _data(
        "edit", e["id"], date="2026-13-45", start_time="25:00", kind=9
    )  # 형식이 틀린 값
    assert _say(client, a, "이상한 값으로 바꿔줘").json()["text"] == modify.NOTHING_TEXT
    fake.data = _data("edit", e["id"], end_time="13:00")  # 시작(14:00)보다 이른 끝
    body = _say(client, a, "치과 끝나는 시간을 1시로").json()
    assert "늦어야" in body["text"] and body["pending_action"] is None


# ---------- 확인 요청은 믿지 않는다 ----------
def test_confirm_revalidates_everything(client, setup, fake):
    a, b, _, _, _ = setup
    mine = _new(client, a)
    theirs = _new(client, b, title="남의 일정")
    edit = {"type": "edit", "event_id": theirs["id"], "changes": {"title": "가로채기"}}
    assert _confirm(client, a, edit).status_code == 404  # 내 줄이 아니면 보이지 않는다
    delete = {"type": "delete", "event_id": theirs["id"]}
    assert _confirm(client, a, delete).status_code == 404
    assert [x["title"] for x in _events(client, b)] == ["남의 일정"]

    bad_kind = {"type": "edit", "event_id": mine["id"], "changes": {"kind": 9}}
    r = _confirm(client, a, bad_kind)
    assert r.status_code == 400 and r.json()["code"] == "invalid_action"
    empty_title = {"type": "edit", "event_id": mine["id"], "changes": {"title": ""}}
    assert _confirm(client, a, empty_title).json()["code"] == "invalid_action"
    nothing = {
        "type": "edit",
        "event_id": mine["id"],
        "changes": {"user_id": "x", "origin_id": "y"},
    }
    assert (
        _confirm(client, a, nothing).json()["code"] == "nothing_to_update"
    )  # 모르는 이름은 버려진다
    no_id = {"type": "delete", "event_id": ""}
    assert _confirm(client, a, no_id).json()["code"] == "invalid_action"
    assert _events(client, a)[0]["title"] == "치과"


def test_personal_info_in_edit_is_masked_out_and_restored(client, setup, fake):
    a, _, _, _, _ = setup
    e = _new(client, a)

    def answer(prompt):
        token = re.search(r"\[PHONE_\d+\]", prompt).group(0)
        return _data("edit", e["id"], title=f"치과 {token}")

    fake.fn = answer
    body = _say(client, a, "치과 이름을 치과 010-1234-5678 로 바꿔줘").json()
    assert "1234-5678" not in fake.calls[0]["prompt"]
    assert body["pending_action"]["changes"]["title"] == "치과 010-1234-5678"
    assert _confirm(client, a, body["pending_action"]).status_code == 200
    assert _events(client, a)[0]["title"] == "치과 010-1234-5678"


# ---------- 공유 대상 바꾸기(원본 주인만) ----------
def _say_in(client, headers, text, channel):
    return client.post("/schedule/agent", json={"text": text, "channel": channel}, headers=headers)


def test_owner_adds_share_target_via_agent(client, setup, fake):
    a, b, _, other, _ = setup
    e = _new(client, a)
    fake.data = _data("edit", e["id"], share_change=True, share_ids=[other])
    body = _say(client, a, "치과 엄마한테도 공유해줘").json()
    assert body["text"] == "이렇게 바꿀까요?"
    by_label = {c["label"]: c for c in body["cards"][0]["data"]["changes"]}
    assert by_label["공유"]["before"] == "없음" and by_label["공유"]["after"] != "없음"
    assert body["pending_action"]["changes"] == {"share_with": [other]}
    assert _events(client, b) == []  # 확인 전에는 공유하지 않는다

    assert _confirm(client, a, body["pending_action"]).status_code == 200
    assert [x["title"] for x in _events(client, b)] == ["치과"]
    assert _events(client, a)[0]["edited_at"] is None  # 공유만 바꾸면 고친 시각을 남기지 않는다


def test_owner_removes_share_target_and_is_warned(client, setup, fake):
    a, b, _, other, _ = setup
    e = _new(client, a, share_with=[other])
    fake.data = _data("edit", e["id"], share_change=True, share_ids=[])
    body = _say(client, a, "치과 공유 풀어줘").json()
    assert "같이 사라져요" in body["text"]
    by_label = {c["label"]: c for c in body["cards"][0]["data"]["changes"]}
    assert by_label["공유"]["before"] != "없음" and by_label["공유"]["after"] == "없음"
    assert len(_events(client, b)) == 1  # 확인 전에는 지우지 않는다

    assert _confirm(client, a, body["pending_action"]).status_code == 200
    assert _events(client, b) == []
    assert [x["title"] for x in _events(client, a)] == ["치과"]


def test_share_change_with_same_targets_or_non_members_changes_nothing(client, setup, fake):
    a, _, _, other, _ = setup
    e = _new(client, a, share_with=[other])
    fake.data = _data("edit", e["id"], share_change=True, share_ids=[other])  # 지금과 같은 대상
    assert _say(client, a, "치과 엄마한테 공유").json()["text"] == modify.NOTHING_TEXT
    e2 = _new(client, a, title="병원")
    fake.data = _data("edit", e2["id"], share_change=True, share_ids=["zzzz"])  # 구성원이 아니다
    body = _say(client, a, "병원 낯선 사람한테 공유").json()
    assert (
        body["pending_action"] is None
    )  # 구성원 아닌 id 는 버려져 "모두 빼기"가 되지만 지금도 비어 있다
    assert body["text"] == modify.NOTHING_TEXT


def test_receiver_cannot_change_share_and_does_not_see_targets(client, setup, fake):
    a, b, me, other, _ = setup
    e = _new(client, a, share_with=[other])
    copy = _events(client, b)[0]
    fake.data = _data("edit", copy["id"], share_change=True, share_ids=[me])
    body = _say(client, b, "치과 공유 바꿔줘").json()
    assert body["text"] == modify.NOT_SHARE_OWNER and body["pending_action"] is None
    assert f"공유:{me}" not in fake.calls[-1]["prompt"]  # 받은 사람에게는 공유 대상이 보이지 않는다
    assert "| 공동" in fake.calls[-1]["prompt"]

    fake.data = _data("query")
    _say(client, a, "치과 언제야")
    assert f"| 공동 | 공유:{other}" in fake.calls[-1]["prompt"]  # 원본 주인은 자기 공유 대상을 안다
    # 받은 사람이 확인 요청을 위조해도 서버가 거부한다
    forged = {"type": "edit", "event_id": copy["id"], "changes": {"share_with": [me]}}
    r = _confirm(client, b, forged)
    assert r.status_code == 403 and r.json()["code"] == "not_share_owner"
    assert e["id"]


def test_share_change_only_in_personal_chat(client, setup, fake):
    a, _, _, other, _ = setup
    e = _new(client, a, share_with=[other])
    fake.data = _data("edit", e["id"], share_change=True, share_ids=[])
    body = _say_in(client, a, "치과 공유 풀어줘", "family").json()
    assert body["text"] == modify.SHARE_PERSONAL_ONLY and body["pending_action"] is None
    line = next(x for x in fake.calls[-1]["prompt"].splitlines() if x.startswith(e["id"]))
    assert line.endswith("| 공동")  # 가족 채팅에는 공유 대상을 보내지 않는다


def test_confirm_rejects_non_member_share_target(client, setup, fake):
    a, _, _, _, _ = setup
    e = _new(client, a)
    forged = {"type": "edit", "event_id": e["id"], "changes": {"share_with": ["zzzz"]}}
    r = _confirm(client, a, forged)
    assert r.status_code == 400 and r.json()["code"] == "invalid_share_target"
