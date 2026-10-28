"""일정: 사람마다 자기 줄, 공유 복사본, 내 줄만 삭제."""

from datetime import UTC, datetime, timedelta

from app.shared.db import SessionLocal
from tests.helpers import join_family, signup

from ..models import Event


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _soon(days: int = 1) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def _titles(client, headers, **params) -> list[str]:
    return [
        x["title"] for x in client.get("/schedule/events", params=params, headers=headers).json()
    ]


def test_schedule_is_mine_unless_shared(client, family):
    a, b, _ = family
    client.post("/schedule/events", json={"title": "치과", "starts_at": _soon()}, headers=a)
    assert _titles(client, a) == ["치과"]
    assert _titles(client, b) == []  # 공유를 고르지 않으면 나만 가진다


def test_share_makes_a_copy_owned_by_the_receiver(client, family):
    a, b, _ = family
    b_id = _me(client, b)
    original = client.post(
        "/schedule/events",
        json={"title": "병원", "starts_at": _soon(), "share_with": [b_id, b_id]},
        headers=a,
    ).json()
    copy = client.get("/schedule/events", headers=b).json()
    assert [x["title"] for x in copy] == ["병원"]
    assert copy[0]["user_id"] == b_id
    assert copy[0]["origin_id"] == original["id"]
    assert copy[0]["created_by"] == original["created_by"]  # 만든 사람은 그대로
    assert _titles(client, a) == ["병원"]  # 같은 사람에게 두 번 줘도 복사본은 하나


def test_share_with_non_member_is_rejected(client, family):
    a, _, _ = family
    outsider = signup(client, "남")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    r = client.post(
        "/schedule/events",
        json={"title": "병원", "starts_at": _soon(), "share_with": [_me(client, outsider)]},
        headers=a,
    )
    assert r.status_code == 400 and r.json()["code"] == "invalid_share_target"
    assert _titles(client, a) == []  # 거절되면 원본도 만들지 않는다


def test_confirm_only_changes_my_own_row(client, family):
    a, b, _ = family
    original = client.post(
        "/schedule/events",
        json={
            "title": "병원",
            "starts_at": _soon(),
            "status": "pending",
            "share_with": [_me(client, b)],
        },
        headers=a,
    ).json()
    copy = client.get("/schedule/events", headers=b).json()[0]
    assert client.post(f"/schedule/events/{copy['id']}/confirm", headers=b).json()["status"] == (
        "confirmed"
    )
    mine = client.get("/schedule/events", headers=a).json()[0]
    assert mine["id"] == original["id"] and mine["status"] == "pending"
    # 남의 줄은 확인할 수 없다
    assert client.post(f"/schedule/events/{mine['id']}/confirm", headers=b).status_code == 404


def test_deleting_original_leaves_copy_and_copy_owner_can_delete_theirs(client, family):
    a, b, _ = family
    original = client.post(
        "/schedule/events",
        json={"title": "병원", "starts_at": _soon(), "share_with": [_me(client, b)]},
        headers=a,
    ).json()
    copy = client.get("/schedule/events", headers=b).json()[0]
    assert client.delete(f"/schedule/events/{original['id']}", headers=a).status_code == 204
    assert client.delete(f"/schedule/events/{original['id']}", headers=a).json()["code"] == (
        "not_found"
    )
    assert _titles(client, a) == []
    assert _titles(client, b) == ["병원"]  # 복사본은 받은 사람 마음
    assert client.delete(f"/schedule/events/{copy['id']}", headers=b).status_code == 204
    assert _titles(client, b) == []
    with SessionLocal() as db:  # 지우지 않고 삭제 시각만 남는다
        assert db.get(Event, original["id"]).deleted_at is not None


def test_cannot_delete_someone_elses_row(client, family):
    a, b, _ = family
    original = client.post(
        "/schedule/events", json={"title": "병원", "starts_at": _soon()}, headers=a
    ).json()
    assert client.delete(f"/schedule/events/{original['id']}", headers=b).status_code == 404
    assert _titles(client, a) == ["병원"]


def test_new_fields_and_starts_at_follow_start_date(client, family):
    a, _, _ = family
    e = client.post(
        "/schedule/events",
        json={
            "title": "  장보기  ",
            "start_date": "2030-01-05",
            "start_time": "10:00:00",
            "end_time": "11:30:00",
            "kind": 2,
            "place": "마트",
            "who_ids": ["u1", "u1"],
            "memo": "우유",
        },
        headers=a,
    ).json()
    assert e["title"] == "장보기" and e["kind"] == 2 and e["place"] == "마트"
    assert e["who_ids"] == ["u1"] and e["memo"] == "우유" and e["note"] == "우유"
    assert (e["start_date"], e["start_time"], e["end_time"]) == (
        "2030-01-05",
        "10:00:00",
        "11:30:00",
    )
    assert e["starts_at"].startswith("2030-01-05T01:00:00")  # 한국 시간 10시 = UTC 1시
    assert e["checked"] is False and e["origin_id"] is None


def test_old_style_request_still_fills_new_columns(client, family):
    a, _, _ = family
    e = client.post(
        "/schedule/events",
        json={"title": "병원", "starts_at": "2030-01-05T01:00:00+00:00", "note": "예약"},
        headers=a,
    ).json()
    assert e["kind"] == 1 and e["memo"] == "예약" and e["place"] == ""
    assert (e["start_date"], e["start_time"]) == ("2030-01-05", "10:00:00")


def test_event_needs_a_time(client, family):
    a, _, _ = family
    assert client.post("/schedule/events", json={"title": "병원"}, headers=a).status_code == 422


def test_ownerless_legacy_rows_are_visible_to_group_but_only_creator_deletes(client, family):
    a, b, group = family
    with SessionLocal() as db:
        db.add(
            Event(
                id="old1",
                group_id=group["id"],
                title="옛 일정",
                starts_at=datetime.now(UTC) + timedelta(days=1),
                created_by=_me(client, a),
            )
        )
        db.commit()
    assert _titles(client, b) == ["옛 일정"]
    r = client.delete("/schedule/events/old1", headers=b)
    assert r.status_code == 403 and r.json()["code"] == "not_owner"
    assert client.delete("/schedule/events/old1", headers=a).status_code == 204
    assert _titles(client, b) == []


def test_schedule_is_scoped_to_group(client, family):
    a, _, _ = family
    e = client.post(
        "/schedule/events", json={"title": "병원", "starts_at": _soon()}, headers=a
    ).json()
    outsider = signup(client, "남")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    assert client.post(f"/schedule/events/{e['id']}/confirm", headers=outsider).status_code == 404


def test_include_past(client, family):
    a, _, _ = family
    client.post("/schedule/events", json={"title": "내일", "starts_at": _soon(1)}, headers=a)
    client.post("/schedule/events", json={"title": "어제", "starts_at": _soon(-1)}, headers=a)
    assert _titles(client, a) == ["내일"]
    assert _titles(client, a, include_past=True) == ["어제", "내일"]


def _new(client, headers, **fields):
    body = {"title": "장보기", "start_date": "2030-01-05", **fields}
    r = client.post("/schedule/events", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _patch(client, headers, event_id, **fields):
    return client.patch(f"/schedule/events/{event_id}", json=fields, headers=headers)


def test_update_changes_values_and_keeps_old_columns_in_sync(client, family):
    a, _, _ = family
    e = _new(client, a, start_time="10:00:00", end_time="11:00:00", place="마트")
    assert e["edited_at"] is None
    r = _patch(
        client,
        a,
        e["id"],
        title="  시장 보기 ",
        start_time="11:00:00",
        end_time="12:30:00",
        place="시장",
        memo="우유",
        kind=2,
        who_ids=["u1", "u1"],
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["title"] == "시장 보기" and out["place"] == "시장" and out["kind"] == 2
    assert out["memo"] == "우유" and out["note"] == "우유" and out["who_ids"] == ["u1"]
    assert (out["start_time"], out["end_time"]) == ("11:00:00", "12:30:00")
    assert out["starts_at"].startswith("2030-01-05T02:00:00")  # 한국 시간 11시 = UTC 2시
    assert out["edited_at"] is not None


def test_update_keeps_what_was_not_sent(client, family):
    a, _, _ = family
    e = _new(client, a, start_time="10:00:00", end_time="11:00:00", place="마트", memo="우유")
    out = _patch(client, a, e["id"], start_date="2030-02-01").json()
    assert out["start_date"] == "2030-02-01"
    assert (out["start_time"], out["end_time"]) == ("10:00:00", "11:00:00")
    assert out["place"] == "마트" and out["memo"] == "우유" and out["title"] == "장보기"
    assert out["starts_at"].startswith("2030-02-01T01:00:00")


def test_update_can_clear_the_time(client, family):
    a, _, _ = family
    e = _new(client, a, start_time="10:00:00", end_time="11:00:00")
    out = _patch(client, a, e["id"], start_time=None).json()
    assert out["start_time"] is None and out["end_time"] is None  # 시간 없음
    assert out["starts_at"].startswith("2030-01-04T15:00:00")  # 그날 0시(한국 시간)


def test_update_rejects_bad_input(client, family):
    a, _, _ = family
    e = _new(client, a, start_time="10:00:00", end_time="11:00:00")
    r = _patch(client, a, e["id"], end_time="09:00:00")
    assert r.status_code == 400 and r.json()["code"] == "invalid_time"
    r = _patch(client, a, e["id"])
    assert r.status_code == 400 and r.json()["code"] == "nothing_to_update"
    assert _patch(client, a, e["id"], title="").status_code == 422
    assert _patch(client, a, e["id"], kind=7).status_code == 422
    assert client.get("/schedule/events", headers=a).json()[0]["end_time"] == "11:00:00"


def test_update_does_not_spread_between_original_and_copy(client, family):
    a, b, _ = family
    original = _new(client, a, share_with=[_me(client, b)])
    copy = client.get("/schedule/events", headers=b).json()[0]
    _patch(client, a, original["id"], title="원본 수정")
    assert _titles(client, b) == ["장보기"]  # 원본을 고쳐도 복사본은 그대로
    assert (
        _patch(client, b, copy["id"], title="내 것").status_code == 200
    )  # 복사본은 받은 사람이 고친다
    assert _titles(client, a) == ["원본 수정"]


def test_update_only_by_the_owner_of_the_row(client, family):
    a, b, group = family
    e = _new(client, a)
    assert (
        _patch(client, b, e["id"], title="남의 것").status_code == 404
    )  # 내 줄이 아니면 보이지 않는다
    with SessionLocal() as db:
        db.add(
            Event(
                id="old2",
                group_id=group["id"],
                title="옛 일정",
                starts_at=datetime.now(UTC) + timedelta(days=1),
                created_by=_me(client, a),
            )
        )
        db.commit()
    r = _patch(client, b, "old2", title="가로채기")
    assert (
        r.status_code == 403 and r.json()["code"] == "not_owner"
    )  # 주인이 없던 옛 일정은 만든 사람만
    assert _patch(client, a, "old2", title="고침").status_code == 200
    assert _patch(client, a, "old2", start_time="09:00:00", end_time="10:00:00").status_code == 200


def test_update_of_deleted_event_is_not_found(client, family):
    a, _, _ = family
    e = _new(client, a)
    client.delete(f"/schedule/events/{e['id']}", headers=a)
    assert _patch(client, a, e["id"], title="되살리기").status_code == 404


def test_set_checked_marks_only_my_row(client, family):
    a, b, _ = family
    original = _new(client, a, share_with=[_me(client, b)])
    assert original["checked"] is False
    r = client.put(f"/schedule/events/{original['id']}/checked", json={"checked": True}, headers=a)
    assert r.status_code == 200 and r.json()["checked"] is True
    assert r.json()["edited_at"] is None  # 일정을 고친 것이 아니다
    again = client.put(
        f"/schedule/events/{original['id']}/checked", json={"checked": True}, headers=a
    )
    assert again.json()["checked"] is True  # 같은 값을 다시 보내도 그대로
    copy = client.get("/schedule/events", headers=b).json()[0]
    assert copy["checked"] is False  # 체크는 각자 자기 줄에서 한다
    done = client.put(f"/schedule/events/{copy['id']}/checked", json={"checked": True}, headers=b)
    assert done.json()["checked"] is True
    off = client.put(
        f"/schedule/events/{original['id']}/checked", json={"checked": False}, headers=a
    )
    assert off.json()["checked"] is False
    assert client.get("/schedule/events", headers=b).json()[0]["checked"] is True


def test_set_checked_rejects_unknown_or_others_rows(client, family):
    a, b, _ = family
    e = _new(client, a)
    assert (
        client.put(
            f"/schedule/events/{e['id']}/checked", json={"checked": True}, headers=b
        ).status_code
        == 404
    )
    assert (
        client.put("/schedule/events/nope/checked", json={"checked": True}, headers=a).status_code
        == 404
    )
    assert client.put(f"/schedule/events/{e['id']}/checked", json={}, headers=a).status_code == 422
    client.delete(f"/schedule/events/{e['id']}", headers=a)
    assert (
        client.put(
            f"/schedule/events/{e['id']}/checked", json={"checked": True}, headers=a
        ).status_code
        == 404
    )


def _topics(client, headers) -> list[dict]:
    return client.get("/schedule/topics", headers=headers).json()


def _add_topic(client, headers, name, color="rose"):
    return client.post("/schedule/topics", json={"name": name, "color": color}, headers=headers)


def test_topics_start_with_default_and_are_mine(client, family):
    a, b, _ = family
    assert [(t["name"], t["color"]) for t in _topics(client, a)] == [("경조사", "rose")]
    r = _add_topic(client, a, " 병원 ", "amber")
    assert r.status_code == 201 and r.json()["name"] == "병원"
    assert [t["name"] for t in _topics(client, a)] == ["경조사", "병원"]
    assert [t["name"] for t in _topics(client, b)] == ["경조사"]  # 사람마다 따로


def test_topic_accepts_all_palette_colors_and_rejects_others(client, family):
    a, _, _ = family
    for color in ("rose", "amber", "green", "sky", "purple"):
        r = _add_topic(client, a, f"c-{color}", color)
        assert r.status_code == 201 and r.json()["color"] == color
    assert _add_topic(client, a, "x", "red").status_code == 422


def test_topic_rejects_duplicate_blank_and_unknown_color(client, family):
    a, _, _ = family
    assert _add_topic(client, a, "병원").status_code == 201
    dup = _add_topic(client, a, "병원", "amber")
    assert dup.status_code == 409 and dup.json()["code"] == "topic_exists"
    assert _add_topic(client, a, "  ").status_code == 422
    assert _add_topic(client, a, "x", "blue").status_code == 422


def test_event_takes_my_topic_and_patch_can_change_and_clear_it(client, family):
    a, b, _ = family
    topic = _topics(client, a)[0]
    ev = _new(client, a, topic_id=topic["id"])
    assert ev["topic_id"] == topic["id"]
    other = _add_topic(client, a, "병원", "amber").json()
    assert _patch(client, a, ev["id"], topic_id=other["id"]).json()["topic_id"] == other["id"]
    assert _patch(client, a, ev["id"], title="새 제목").json()["topic_id"] == other["id"]
    assert _patch(client, a, ev["id"], topic_id=None).json()["topic_id"] is None

    b_topic = _topics(client, b)[0]
    bad = client.post(
        "/schedule/events",
        json={"title": "x", "start_date": "2030-01-05", "topic_id": b_topic["id"]},
        headers=a,
    )
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_topic"
    assert _patch(client, a, ev["id"], topic_id="nope").status_code == 400


def test_share_copy_has_no_topic(client, family):
    a, b, _ = family
    topic = _topics(client, a)[0]
    _new(client, a, topic_id=topic["id"], share_with=[_me(client, b)])
    [mine] = client.get("/schedule/events", headers=a).json()
    [copy] = client.get("/schedule/events", headers=b).json()
    assert mine["topic_id"] == topic["id"]
    assert copy["topic_id"] is None


def test_deleting_topic_keeps_events_and_does_not_recreate_default(client, family):
    a, b, _ = family
    topic = _topics(client, a)[0]
    ev = _new(client, a, topic_id=topic["id"])
    assert client.delete(f"/schedule/topics/{topic['id']}", headers=a).status_code == 204
    assert _topics(client, a) == []  # 지운 기본 주제는 다시 생기지 않는다
    [got] = client.get("/schedule/events", headers=a).json()
    assert got["id"] == ev["id"] and got["topic_id"] is None
    assert _patch(client, a, ev["id"], topic_id=topic["id"]).status_code == 400
    assert client.delete(f"/schedule/topics/{topic['id']}", headers=a).status_code == 404
    b_topic = _topics(client, b)[0]
    assert client.delete(f"/schedule/topics/{b_topic['id']}", headers=a).status_code == 404


def _third(client, owner, group):
    c = signup(client, "민수")
    join_family(client, owner, group["invite_code"], c)
    return c


def _sharing(client, headers, event_id):
    return client.get(f"/schedule/events/{event_id}/sharing", headers=headers)


def test_sharing_original_lists_recipients_and_copy_shows_origin(client, family):
    a, b, group = family
    c = _third(client, a, group)
    a_id, b_id, c_id = _me(client, a), _me(client, b), _me(client, c)
    original = _new(client, a, share_with=[b_id, c_id])
    assert _sharing(client, a, original["id"]).json() == {
        "shared_by": None,
        "shared_with": [b_id, c_id],
    }
    copy = client.get("/schedule/events", headers=b).json()[0]
    # 복사본: 보낸 사람은 원본 주인, 받은 사람에는 나와 형제 복사본이 들어간다
    assert _sharing(client, b, copy["id"]).json() == {
        "shared_by": a_id,
        "shared_with": [b_id, c_id],
    }


def test_sharing_keeps_deleted_copy_and_reports_origin_after_original_deleted(client, family):
    a, b, group = family
    c = _third(client, a, group)
    a_id, b_id, c_id = _me(client, a), _me(client, b), _me(client, c)
    original = _new(client, a, share_with=[b_id, c_id])
    copy = client.get("/schedule/events", headers=b).json()[0]
    assert client.delete(f"/schedule/events/{copy['id']}", headers=b).status_code == 204
    assert _sharing(client, a, original["id"]).json()["shared_with"] == [b_id, c_id]
    c_copy = client.get("/schedule/events", headers=c).json()[0]
    assert client.delete(f"/schedule/events/{original['id']}", headers=a).status_code == 204
    assert _sharing(client, c, c_copy["id"]).json() == {
        "shared_by": a_id,
        "shared_with": [b_id, c_id],
    }


def test_sharing_of_unshared_event_is_empty_and_others_get_404(client, family):
    a, b, _ = family
    e = _new(client, a)
    assert _sharing(client, a, e["id"]).json() == {"shared_by": None, "shared_with": []}
    assert _sharing(client, b, e["id"]).status_code == 404  # 남의 줄
    assert _sharing(client, a, "nope").status_code == 404
