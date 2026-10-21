"""돌봄 기록과 오늘 요약."""


def test_care_record_overwrites_same_day_and_summarizes(client, family):
    a, b, _ = family
    body = {"subject": "어머니", "kind": "condition", "value": "보통이에요"}
    first = client.put("/care/records", json=body, headers=a).json()
    assert first["replaced"] is False
    second = client.put(
        "/care/records", json={**body, "value": "좋아요", "note": "아침 먹었어"}, headers=b
    ).json()
    assert second["replaced"] is True and second["record"]["id"] == first["record"]["id"]
    client.put(
        "/care/records", json={"subject": "어머니", "kind": "meal", "value": "먹었어요"}, headers=a
    )
    s = client.get("/care/summary/today", headers=a).json()
    assert {r["kind"]: r["value"] for r in s["records"]} == {
        "condition": "좋아요",
        "meal": "먹었어요",
    }
    assert s["missing"] == ["medication", "walk"]
    assert client.put("/care/records", json={**body, "kind": "bogus"}, headers=a).status_code == 422
