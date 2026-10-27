"""같이해요 부탁: 보내기·목록·답하기(내 일정 생성)·취소."""

from datetime import date, timedelta

from app.shared.db import SessionLocal

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
    assert e["who_ids"] == [a_id] and e["origin_id"] is None and e["topic_id"] is None
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


def test_cancel_by_sender_only_while_waiting(client, family):
    a, b, _ = family
    req = _send(client, a, [_me(client, b)]).json()
    assert _cancel(client, b, req["id"]).status_code == 403
    out = _cancel(client, a, req["id"])
    assert out.status_code == 200 and out.json()["canceled"] is True
    assert _cancel(client, a, req["id"]).json()["canceled"] is True  # 다시 취소해도 그대로
    r = _answer(client, b, req["id"])
    assert r.status_code == 400 and r.json()["code"] == "request_canceled"
    assert _events(client, b) == []


def test_cancel_refused_after_accept(client, family):
    a, b, _ = family
    req = _send(client, a, [_me(client, b)]).json()
    _answer(client, b, req["id"])
    r = _cancel(client, a, req["id"])
    assert r.status_code == 400 and r.json()["code"] == "already_accepted"
    assert len(_events(client, b)) == 1  # 만들어진 일정은 그대로
    # 어렵겠어요로 바꾸면 기다리는 사람이 없으니 취소할 수 있다
    _answer(client, b, req["id"], answer="declined", kind=None)
    assert _cancel(client, a, req["id"]).json()["canceled"] is True


def test_other_family_cannot_touch_request(client, family, other_family):
    a, b, _ = family
    req = _send(client, a, [_me(client, b)]).json()
    assert _cancel(client, other_family, req["id"]).status_code == 404
    assert _answer(client, other_family, req["id"]).status_code == 404
    assert _cancel(client, a, "nope").status_code == 404
