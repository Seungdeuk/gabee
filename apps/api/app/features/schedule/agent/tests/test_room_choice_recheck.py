"""가족방에서 만든 되묻기(선택) 상태를 실행할 때 권한을 **실행 시점의 상태로** 다시 검사한다(작업 C, 2026-11-25).

가족방에서 같은 이름의 일정·부탁 둘을 두고 "어느 쪽인가요?"라고 되물은 뒤, 사용자가 "첫 번째"라고 답하기 전에 상태가 바뀔 수 있다.
1. 일정 공유가 좁혀지거나 풀림  2. 가족 구성원이 새로 들어오거나 나감  3. 부탁의 받는 사람이 바뀜  4. 고른 대상이 지워지거나 취소됨
권한이 사라진 대상은 방 답·카드에 제목·id 가 실리지 않고, 바뀌거나 지워지지도 않아야 한다. 되물은 순서("첫 번째")는 그대로 지켜서,
사라진 후보 자리에 다른 후보가 밀려 들어와 엉뚱한 대상이 처리되지 않게 한다. 실제 Anthropic 은 부르지 않는다(가짜 모델).
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.features.schedule.agent import register as register_mod
from app.shared import ai_guard
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

FIRST = "온 가족 외식 일정"
SECOND = "온 가족 소풍 일정"
REQ = "다 같이 장보기 부탁"
NOT_SCHEDULE = {"intent": "not_schedule", "reply": "", "event_ids": []}


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.data = dict(NOT_SCHEDULE)

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
def three(client, family):
    """가족 구성원 A(지민)·B(수진)·C(민수). 그룹 정보도 돌려준다(새 구성원 초대용)."""
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
    return a, b, c, ids, group


def _say(client, headers, text, channel="family"):
    r = client.post("/schedule/agent", json={"text": text, "channel": channel}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _event(client, headers, title, days, share_to):
    when = (datetime.now(UTC) + timedelta(days=days)).isoformat()
    r = client.post(
        "/schedule/events",
        json={"title": title, "starts_at": when, "share_with": list(share_to)},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _my_event_ids(client, headers):
    return {e["id"] for e in client.get("/schedule/events", headers=headers).json()}


def _ask_delete_in_room(client, fake, a, ids, channel="family"):
    """A 가 가족 전원과 공유한 두 일정(첫째 +2일, 둘째 +5일)을 두고 가족방에서 "그 일정 지워줘" → 되묻기."""
    e1 = _event(client, a, FIRST, 2, [ids["b"], ids["c"]])
    e2 = _event(client, a, SECOND, 5, [ids["b"], ids["c"]])
    fake.data = {
        "intent": "delete",
        "reply": "",
        "event_ids": [e1["id"], e2["id"]],  # 모델이 같은 일로 본 일정(related)
        "target_id": e1["id"],
    }
    asked = _say(client, a, "가족 일정 지워줘", channel)
    assert asked.get("pending_action") is None and "어느 쪽" in asked["text"], asked
    fake.data = dict(NOT_SCHEDULE)
    return e1, e2


def _hidden(body, event):
    dumped = str(body)
    return event["title"] not in dumped and event["id"] not in dumped


# ---------- 1. 일정 공유가 좁혀지거나 풀림 ----------
def test_narrowed_sharing_after_the_question_blocks_the_choice_in_the_family_room(
    client, three, fake
):
    a, b, c, ids, _ = three
    e1, e2 = _ask_delete_in_room(client, fake, a, ids)
    r = client.patch(f"/schedule/events/{e1['id']}", json={"share_with": [ids["b"]]}, headers=a)
    assert r.status_code == 200, r.text  # 이제 C 는 첫째 일정을 볼 수 없다
    body = _say(client, a, "첫 번째")
    assert _hidden(body, e1) and "지웠어요" not in body["text"]
    assert {e1["id"], e2["id"]} <= _my_event_ids(client, a)  # 아무것도 지워지지 않았다


def test_unshared_event_after_the_question_blocks_the_choice_in_the_family_room(
    client, three, fake
):
    a, b, c, ids, _ = three
    e1, e2 = _ask_delete_in_room(client, fake, a, ids)
    r = client.patch(f"/schedule/events/{e1['id']}", json={"share_with": []}, headers=a)
    assert r.status_code == 200, r.text  # 나만 보는 일정이 됐다(shared=False)
    body = _say(client, a, "첫 번째")
    assert _hidden(body, e1) and "지웠어요" not in body["text"]
    assert {e1["id"], e2["id"]} <= _my_event_ids(client, a)


def test_an_unaffected_option_still_works_and_keeps_its_position(client, three, fake):
    """첫째 일정의 공유가 좁혀져도 "두 번째"는 여전히 둘째 일정이다(정상 공동 일정 처리 유지)."""
    a, b, c, ids, _ = three
    e1, e2 = _ask_delete_in_room(client, fake, a, ids)
    client.patch(f"/schedule/events/{e1['id']}", json={"share_with": [ids["b"]]}, headers=a)
    body = _say(client, a, "두 번째")
    assert "지웠어요" in body["text"] and SECOND in body["text"] and _hidden(body, e1)
    left = _my_event_ids(client, a)
    assert e1["id"] in left and e2["id"] not in left


# ---------- 2. 가족 구성원이 들어오거나 나감 ----------
def test_a_new_member_who_cannot_see_the_events_blocks_the_choice(client, three, fake):
    a, b, c, ids, group = three
    e1, e2 = _ask_delete_in_room(client, fake, a, ids)
    d = signup(client, "새가족")
    join_family(client, a, group["invite_code"], d)  # 새 구성원은 두 일정을 받은 적이 없다
    body = _say(client, a, "첫 번째")
    assert _hidden(body, e1) and _hidden(body, e2) and "지웠어요" not in body["text"]
    assert {e1["id"], e2["id"]} <= _my_event_ids(client, a)


def test_a_member_leaving_keeps_the_choice_working_for_the_remaining_room(client, three, fake):
    """구성원이 나가면 남은 방 구성원 모두가 여전히 볼 수 있는 일정이라 그대로 처리된다."""
    a, b, c, ids, _ = three
    e1, e2 = _ask_delete_in_room(client, fake, a, ids)
    r = client.post("/family-group/groups/me/leave", headers=c)
    assert r.status_code == 204, r.text
    body = _say(client, a, "첫 번째")
    assert "지웠어요" in body["text"] and FIRST in body["text"]
    left = _my_event_ids(client, a)
    assert e1["id"] not in left and e2["id"] in left


# ---------- 3. 부탁의 받는 사람이 바뀜 ----------
def _send(client, headers, to, days):
    day = (register_mod.today() + timedelta(days=days)).isoformat()
    r = client.post(
        "/schedule/requests",
        json={"title": REQ, "start_date": day, "to_ids": to},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _req(action, target, **extra):
    base = {
        "action": action, "target_id": target, "request_ids": [], "title": "", "date": "",
        "start_time": "", "end_time": "", "place": "", "memo": "", "to_ids": [], "date_ambiguous": False,
    }  # fmt: skip
    base.update(extra)
    return {"intent": "request", "reply": "", "event_ids": [], "request": base}


def _ask_request_in_room(client, fake, a, ids, action="cancel", **extra):
    r1 = _send(client, a, [ids["b"], ids["c"]], 3)
    r2 = _send(client, a, [ids["b"], ids["c"]], 10)
    fake.data = _req(action, r1["id"], **extra)
    asked = _say(client, a, "그 부탁 바꿔줘")
    assert asked.get("pending_action") is None and "어느 쪽" in asked["text"], asked
    fake.data = dict(NOT_SCHEDULE)
    return r1, r2


def _requests(client, headers):
    return {r["id"]: r for r in client.get("/schedule/requests", headers=headers).json()}


def test_narrowed_request_recipients_block_a_cancel_choice_in_the_family_room(client, three, fake):
    a, b, c, ids, _ = three
    r1, r2 = _ask_request_in_room(client, fake, a, ids)
    r = client.put(
        f"/schedule/requests/{r1['id']}/recipients", json={"to_ids": [ids["b"]]}, headers=a
    )
    assert r.status_code == 200, r.text  # 이제 C 는 첫째 부탁을 볼 수 없다
    body = _say(client, a, "첫 번째")
    assert r1["id"] not in str(body) and REQ not in str(body)
    assert body.get("pending_action") is None and not body["cards"]
    assert not any(x["canceled"] for x in _requests(client, a).values())


def test_narrowed_request_recipients_block_a_memo_edit_choice_in_the_family_room(
    client, three, fake
):
    a, b, c, ids, _ = three
    r1, r2 = _ask_request_in_room(client, fake, a, ids, action="edit", memo="새 메모입니다")
    client.put(f"/schedule/requests/{r1['id']}/recipients", json={"to_ids": [ids["b"]]}, headers=a)
    body = _say(client, a, "첫 번째")
    assert r1["id"] not in str(body) and REQ not in str(body)
    assert _requests(client, a)[r1["id"]]["memo"] != "새 메모입니다"  # 바뀌지 않았다


# ---------- 4. 고른 대상이 지워지거나 취소됨 ----------
def test_a_deleted_target_is_not_replaced_by_the_next_option(client, three, fake):
    """첫째 일정이 지워진 뒤 "첫 번째"라고 답해도 둘째 일정이 대신 지워지지 않는다."""
    a, b, c, ids, _ = three
    e1, e2 = _ask_delete_in_room(client, fake, a, ids)
    assert client.delete(f"/schedule/events/{e1['id']}", headers=a).status_code == 204
    body = _say(client, a, "첫 번째")
    assert "지웠어요" not in body["text"] and _hidden(body, e1) and _hidden(body, e2)
    assert e2["id"] in _my_event_ids(client, a)


def test_a_deleted_target_is_not_replaced_by_the_next_option_in_the_personal_chat(
    client, three, fake
):
    """되물은 순서를 지키는 것은 개인 채팅에도 같다(지워진 첫째 자리에 둘째가 밀려 들어와 지워지지 않는다)."""
    a, b, c, ids, _ = three
    e1, e2 = _ask_delete_in_room(client, fake, a, ids, channel="personal")
    assert client.delete(f"/schedule/events/{e1['id']}", headers=a).status_code == 204
    body = _say(client, a, "첫 번째", "personal")
    assert "지웠어요" not in body["text"]
    assert e2["id"] in _my_event_ids(client, a)


def test_a_canceled_request_is_not_replaced_by_the_next_option(client, three, fake):
    a, b, c, ids, _ = three
    r1, r2 = _ask_request_in_room(client, fake, a, ids)
    assert client.post(f"/schedule/requests/{r1['id']}/cancel", headers=a).status_code == 200
    body = _say(client, a, "첫 번째")
    assert body.get("pending_action") is None and r2["id"] not in str(body)
    assert not _requests(client, a)[r2["id"]]["canceled"]


# ---------- 정상 동작 유지 ----------
def test_the_family_room_choice_still_deletes_the_picked_shared_event(client, three, fake):
    a, b, c, ids, _ = three
    e1, e2 = _ask_delete_in_room(client, fake, a, ids)
    body = _say(client, a, "첫 번째")
    assert "지웠어요" in body["text"] and FIRST in body["text"]
    left = _my_event_ids(client, a)
    assert e1["id"] not in left and e2["id"] in left


def test_the_family_room_request_choice_still_asks_to_cancel_the_picked_request(
    client, three, fake
):
    a, b, c, ids, _ = three
    r1, r2 = _ask_request_in_room(client, fake, a, ids)
    body = _say(client, a, "첫 번째")
    assert body["pending_action"]["request_id"] == r1["id"]


def test_the_personal_chat_choice_still_works_with_partially_shared_events(client, three, fake):
    """개인 채팅은 방 권한과 상관없다: 공유가 좁혀져도 내 일정이라 고른 대로 처리된다."""
    a, b, c, ids, _ = three
    e1, e2 = _ask_delete_in_room(client, fake, a, ids, channel="personal")
    client.patch(f"/schedule/events/{e1['id']}", json={"share_with": [ids["b"]]}, headers=a)
    body = _say(client, a, "첫 번째", "personal")
    assert "지웠어요" in body["text"] and FIRST in body["text"]
    assert e1["id"] not in _my_event_ids(client, a)
