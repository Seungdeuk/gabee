"""일정: 사람마다 자기 줄, 공유 복사본, 내 줄만 삭제."""

from datetime import UTC, datetime, timedelta

from app.shared.db import SessionLocal
from tests.helpers import signup

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
