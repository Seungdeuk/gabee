"""같이해요 부탁: 보내기·목록·답하기(내 일정 생성)·취소."""

from datetime import date, timedelta

from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

from ..models import Event


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _day(days: int = 3) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _send(client, headers, to, **over):
    body = {"title": "병원 같이 가요", "start_date": _day(), "to_ids": to, **over}
    return client.post("/schedule/requests", json=body, headers=headers)


def _answer(client, headers, rid, answer="accepted", kind=1):
    return client.post(
        f"/schedule/requests/{rid}/answer", json={"answer": answer, "kind": kind}, headers=headers
    )


def _cancel(client, headers, rid):
    return client.post(f"/schedule/requests/{rid}/cancel", headers=headers)


def _events(client, headers) -> list[dict]:
    return client.get("/schedule/events", params={"include_past": True}, headers=headers).json()


def test_send_returns_request_with_waiting_recipients(client, family):
    a, b, _ = family
    a_id, b_id = _me(client, a), _me(client, b)
    r = _send(client, a, [b_id, b_id], place=" 서울병원 ", start_time="09:30", end_time="10:30")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["from_id"] == a_id and body["canceled"] is False
    assert body["place"] == "서울병원"
    assert body["start_time"] == "09:30:00" and body["end_time"] == "10:30:00"
    assert body["recipients"] == [{"user_id": b_id, "status": "waiting"}]  # 중복은 하나로
    assert body["my_event_id"] is None


def test_send_validation(client, family, other_family):
    a, b, _ = family
    a_id, b_id = _me(client, a), _me(client, b)
    outsider = _me(client, other_family)
    for to in ([a_id], [outsider], [b_id, outsider]):
        r = _send(client, a, to)
        assert r.status_code == 400 and r.json()["code"] == "invalid_recipients", to
    for times in ({"end_time": "10:00"}, {"start_time": "10:00", "end_time": "09:00"}):
        r = _send(client, a, [b_id], **times)
        assert r.status_code == 400 and r.json()["code"] == "invalid_time", times
    assert _send(client, a, []).status_code == 422
    assert _send(client, a, [b_id], title="  ").status_code == 422
    assert client.get("/schedule/requests", headers=a).json() == []  # 거절되면 만들지 않는다


def test_list_shows_sent_and_received_only(client, family, other_family):
    a, b, _ = family
    first = _send(client, a, [_me(client, b)], title="첫째").json()
    second = _send(client, b, [_me(client, a)], title="둘째").json()
    assert {x["id"] for x in client.get("/schedule/requests", headers=a).json()} == {
        first["id"],
        second["id"],
    }
    # 남의 가족은 아무것도 못 본다
    assert client.get("/schedule/requests", headers=other_family).json() == []


def test_accept_creates_my_event_only(client, family):
    a, b, _ = family
    a_id, b_id = _me(client, a), _me(client, b)
    req = _send(
        client, a, [b_id], memo="메모", place="병원", start_time="09:00", end_time="10:00"
    ).json()
    r = _answer(client, b, req["id"], kind=1)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["recipients"] == [{"user_id": b_id, "status": "accepted"}]
    events = _events(client, b)
    assert len(events) == 1 and out["my_event_id"] == events[0]["id"]
    e = events[0]
    assert (e["user_id"], e["created_by"], e["kind"], e["source"]) == (b_id, b_id, 1, "request")
    assert (e["title"], e["place"], e["memo"]) == ("병원 같이 가요", "병원", "메모")
    assert (e["start_date"], e["start_time"], e["end_time"]) == (
        req["start_date"],
        "09:00:00",
        "10:00:00",
    )
    assert (
        e["shared"] is True
        and e["shared_ids"] == [a_id]
        and e["origin_id"] is None
        and e["topic_id"] is None
    )
    assert "request_id" not in e
    assert _events(client, a) == []  # 보낸 사람에게는 일정이 생기지 않는다
    mine = client.get("/schedule/requests", headers=a).json()[0]
    assert mine["recipients"][0]["status"] == "accepted" and mine["my_event_id"] is None


def test_accept_requires_kind_and_only_recipient_can_answer(client, family, other_family):
    a, b, _ = family
    req = _send(client, a, [_me(client, b)]).json()
    r = client.post(
        f"/schedule/requests/{req['id']}/answer", json={"answer": "accepted"}, headers=b
    )
    assert r.status_code == 400 and r.json()["code"] == "kind_required"
    assert _answer(client, a, req["id"]).status_code == 404  # 보낸 사람은 답할 수 없다
    assert _answer(client, other_family, req["id"]).status_code == 404
    assert _events(client, b) == []


def test_all_day_request_as_todo_clears_times(client, family):
    a, b, _ = family
    req = _send(client, a, [_me(client, b)], start_time="00:00", end_time="23:59").json()
    _answer(client, b, req["id"], kind=2)
    e = _events(client, b)[0]
    assert e["kind"] == 2 and e["start_time"] is None and e["end_time"] is None
    # 약속으로 바꿔 받으면 종일 그대로
    _answer(client, b, req["id"], kind=1)
    live = _events(client, b)
    assert len(live) == 1 and live[0]["kind"] == 1
    assert (live[0]["start_time"], live[0]["end_time"]) == ("00:00:00", "23:59:00")


def test_switch_to_declined_deletes_my_event(client, family):
    a, b, _ = family
    req = _send(client, a, [_me(client, b)]).json()
    _answer(client, b, req["id"])
    assert len(_events(client, b)) == 1
    out = _answer(client, b, req["id"], answer="declined", kind=None).json()
    assert out["recipients"][0]["status"] == "declined" and out["my_event_id"] is None
    assert _events(client, b) == []
    # 어렵겠어요도 보낸 사람에게 보인다
    mine = client.get("/schedule/requests", headers=a).json()[0]
    assert mine["recipients"][0]["status"] == "declined"


def test_reaccept_with_other_kind_replaces_event(client, family):
    a, b, _ = family
    req = _send(client, a, [_me(client, b)]).json()
    first = _answer(client, b, req["id"], kind=1).json()["my_event_id"]
    second = _answer(client, b, req["id"], kind=2).json()["my_event_id"]
    assert second and second != first
    assert [(x["id"], x["kind"]) for x in _events(client, b)] == [(second, 2)]
    with SessionLocal() as db:
        assert db.get(Event, first).deleted_at is not None  # 이전 일정은 소프트 삭제
    # 같은 종류로 다시 수락하면 일정을 그대로 둔다
    assert _answer(client, b, req["id"], kind=2).json()["my_event_id"] == second


def test_cannot_change_answer_after_date_passed(client, family):
    a, b, _ = family
    req = _send(client, a, [_me(client, b)], start_date=_day(-2)).json()
    assert _answer(client, b, req["id"]).status_code == 200  # 첫 답은 날짜와 무관
    r = _answer(client, b, req["id"], answer="declined", kind=None)
    assert r.status_code == 400 and r.json()["code"] == "answer_locked"
    assert len(_events(client, b)) == 1


def test_cancel_by_sender_only(client, family):
    a, b, _ = family
    req = _send(client, a, [_me(client, b)]).json()
    assert _cancel(client, b, req["id"]).status_code == 403
    out = _cancel(client, a, req["id"])
    assert out.status_code == 200 and out.json()["canceled"] is True
    assert _cancel(client, a, req["id"]).json()["canceled"] is True  # 다시 취소해도 그대로
    r = _answer(client, b, req["id"])
    assert r.status_code == 400 and r.json()["code"] == "request_canceled"
    assert _events(client, b) == []


def test_cancel_after_accept_deletes_accepted_events(client, family):
    a, b, _ = family
    req = _send(client, a, [_me(client, b)]).json()
    _answer(client, b, req["id"])
    assert len(_events(client, b)) == 1
    out = _cancel(client, a, req["id"])
    assert (
        out.status_code == 200 and out.json()["canceled"] is True
    )  # 수락한 사람이 있어도 취소된다
    assert _events(client, b) == []  # 수락해서 만든 일정도 같이 지워진다
    assert _cancel(client, a, req["id"]).status_code == 200  # 다시 취소해도 그대로


def _member(client, owner, group, name) -> dict:
    """같은 가족에 구성원을 더 들이고 그 헤더를 돌려준다."""
    joiner = signup(client, name)
    join_family(client, owner, group["invite_code"], joiner)
    return joiner


def _recipients(client, headers, rid, to_ids):
    return client.put(
        f"/schedule/requests/{rid}/recipients", json={"to_ids": to_ids}, headers=headers
    )


def test_change_recipients_add_and_remove(client, family):
    a, b, group = family
    c = _member(client, a, group, "민수")
    b_id, c_id = _me(client, b), _me(client, c)
    rid = _send(client, a, [b_id]).json()["id"]
    assert _events(client, c) == [] and client.get("/schedule/requests", headers=c).json() == []

    out = _recipients(client, a, rid, [b_id, c_id])
    assert out.status_code == 200, out.text
    body = out.json()
    assert [r["user_id"] for r in body["recipients"]] == [b_id, c_id]
    assert {r["status"] for r in body["recipients"]} == {"waiting"}
    assert body["edited_at"] is not None
    assert len(client.get("/schedule/requests", headers=c).json()) == 1  # 새로 든 사람에게 보인다

    out = _recipients(client, a, rid, [c_id])  # 답하지 않은 b 를 뺀다
    assert [r["user_id"] for r in out.json()["recipients"]] == [c_id]
    assert client.get("/schedule/requests", headers=b).json() == []  # 빠진 사람은 더 못 본다
    assert _answer(client, b, rid).status_code == 404


def test_remove_accepted_recipient_deletes_their_event_and_readd_is_new(client, family):
    a, b, group = family
    c = _member(client, a, group, "민수")
    b_id, c_id = _me(client, b), _me(client, c)
    rid = _send(client, a, [b_id, c_id]).json()["id"]
    _answer(client, b, rid)
    _answer(client, c, rid)
    assert len(_events(client, b)) == 1 and len(_events(client, c)) == 1

    _recipients(client, a, rid, [c_id])  # 수락한 b 를 뺀다
    assert _events(client, b) == []  # b 의 수락 일정이 같이 지워진다
    assert len(_events(client, c)) == 1  # 남은 사람의 일정은 그대로
    assert client.get("/schedule/requests", headers=b).json() == []

    out = _recipients(client, a, rid, [b_id, c_id])  # 다시 넣으면 새 부탁으로 간다
    status = {r["user_id"]: r["status"] for r in out.json()["recipients"]}
    assert status == {c_id: "accepted", b_id: "waiting"}
    assert _events(client, b) == []
    assert _answer(client, b, rid).status_code == 200
    assert len(_events(client, b)) == 1


def test_change_recipients_no_change_keeps_edited_at_empty(client, family):
    a, b, _ = family
    b_id = _me(client, b)
    rid = _send(client, a, [b_id]).json()["id"]
    out = _recipients(client, a, rid, [b_id])
    assert out.status_code == 200 and out.json()["edited_at"] is None


def test_change_recipients_rules(client, family, other_family):
    a, b, group = family
    a_id, b_id = _me(client, a), _me(client, b)
    outsider = _me(client, other_family)
    rid = _send(client, a, [b_id]).json()["id"]
    assert _recipients(client, a, rid, []).status_code == 422  # 최소 1명
    for to in ([a_id], [outsider], [b_id, outsider]):
        r = _recipients(client, a, rid, to)
        assert r.status_code == 400 and r.json()["code"] == "invalid_recipients", to
    r = _recipients(client, b, rid, [b_id])  # 받는 사람은 못 바꾼다
    assert r.status_code == 403 and r.json()["code"] == "not_owner"
    assert _recipients(client, other_family, rid, [b_id]).status_code == 404
    assert _recipients(client, a, "nope", [b_id]).status_code == 404
    c = _member(client, a, group, "민수")
    _cancel(client, a, rid)
    r = _recipients(client, a, rid, [b_id, _me(client, c)])
    assert r.status_code == 400 and r.json()["code"] == "request_canceled"


def test_recipient_sees_only_self_and_accepted_others(client, family):
    a, b, group = family
    c, d = _member(client, a, group, "민수"), _member(client, a, group, "하윤")
    b_id, c_id, d_id = _me(client, b), _me(client, c), _me(client, d)
    rid = _send(client, a, [b_id, c_id, d_id]).json()["id"]

    def seen(headers):
        got = client.get("/schedule/requests", headers=headers).json()[0]["recipients"]
        return {r["user_id"]: r["status"] for r in got}

    assert seen(a) == {b_id: "waiting", c_id: "waiting", d_id: "waiting"}  # 보낸 사람은 전원
    assert seen(b) == {b_id: "waiting"}  # 받는 사람은 자기 줄만
    _answer(client, c, rid)
    assert seen(b) == {b_id: "waiting", c_id: "accepted"}  # 수락한 사람은 보인다
    _answer(client, d, rid, answer="declined", kind=None)
    assert seen(b) == {b_id: "waiting", c_id: "accepted"}  # 거절한 사람은 안 보인다
    assert seen(d) == {c_id: "accepted", d_id: "declined"}
    out = _answer(client, b, rid).json()  # 답한 응답도 같은 규칙
    assert {r["user_id"] for r in out["recipients"]} == {b_id, c_id}


def test_other_family_cannot_touch_request(client, family, other_family):
    a, b, _ = family
    req = _send(client, a, [_me(client, b)]).json()
    assert _cancel(client, other_family, req["id"]).status_code == 404
    assert _answer(client, other_family, req["id"]).status_code == 404
    assert _cancel(client, a, "nope").status_code == 404


def test_accepted_request_event_is_shared_with_the_sender(client, family):
    a, b, _ = family
    a_id = _me(client, a)
    rid = _send(client, a, [_me(client, b)]).json()["id"]
    _answer(client, b, rid)
    mine = client.get("/schedule/events", headers=b).json()
    assert len(mine) == 1
    assert mine[0]["shared"] is True and mine[0]["shared_ids"] == [a_id]  # 부탁도 공동 일정
    assert (
        client.get("/schedule/events", headers=a).json() == []
    )  # 보낸 사람은 일정이 생기지 않는다
