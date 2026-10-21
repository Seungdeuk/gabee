"""가족 공동 일정."""

from datetime import UTC, datetime, timedelta

from tests.helpers import signup


def test_schedule_create_confirm_delete(client, family):
    a, b, _ = family
    soon = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    e = client.post(
        "/schedule/events",
        json={"title": "병원", "starts_at": soon, "status": "pending"},
        headers=a,
    ).json()
    client.post("/schedule/events", json={"title": "지난 일정", "starts_at": past}, headers=a)
    assert [x["title"] for x in client.get("/schedule/events", headers=b).json()] == ["병원"]
    assert len(client.get("/schedule/events", params={"include_past": True}, headers=b).json()) == 2
    assert (
        client.post(f"/schedule/events/{e['id']}/confirm", headers=b).json()["status"]
        == "confirmed"
    )
    assert client.delete(f"/schedule/events/{e['id']}", headers=a).status_code == 204
    assert client.delete(f"/schedule/events/{e['id']}", headers=a).json()["code"] == "not_found"


def test_schedule_is_scoped_to_group(client, family):
    a, _, _ = family
    soon = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    e = client.post("/schedule/events", json={"title": "병원", "starts_at": soon}, headers=a).json()
    outsider = signup(client, "남")
    client.post("/family-group/groups", json={"name": "다른 가족"}, headers=outsider)
    assert client.post(f"/schedule/events/{e['id']}/confirm", headers=outsider).status_code == 404
