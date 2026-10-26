"""정산 규칙: 미정산 지출은 잔액·송금에서 제외, 자녀 대상 정산은 미성년 자녀가 있을 때만 부모님이 부담."""

from tests.helpers import join_family, signup


def _family(client, family):
    """엄마(parent) + 지민·수진(child). (지민 헤더, 헤더 모음, id 모음)."""
    a, b, group = family
    mom = signup(client, "엄마", role="parent")
    join_family(client, a, group["invite_code"], mom)
    members = client.get("/family-group/groups/me", headers=a).json()["members"]
    ids = {m["name"]: m["id"] for m in members}
    return a, {"지민": a, "수진": b, "엄마": mom}, ids


def _expense(client, headers, amount, title="학원비"):
    r = client.post(
        "/billing/expenses",
        json={"title": title, "amount": amount, "date": "2026-10-12"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _settlement(client, headers):
    return client.get("/billing/settlement", params={"month": "2026-10"}, headers=headers).json()


def _settle(client, headers, ids, tag, participants=None):
    body = {"month": "2026-10", "expense_ids": ids, "tag": tag}
    if participants is not None:
        body["participants"] = participants
    return client.post("/billing/settlement/tag", json=body, headers=headers)


def _tags(client, headers):
    return {t["key"]: t for t in client.get("/billing/settlement/tags", headers=headers).json()}


def test_unsettled_expenses_are_excluded_from_settlement_but_not_from_the_month_summary(
    client, family
):
    a, hdr, ids = _family(client, family)
    e = _expense(client, hdr["엄마"], 30000, "병원비")
    s = _settlement(client, a)
    assert s["transfers"] == [] and all(b["balance"] == 0 and b["paid"] == 0 for b in s["balances"])
    assert (s["unsettled_count"], s["unsettled_total"]) == (1, 30000)
    # 월 요약(/billing/summary)은 미정산 지출까지 보여 주는 미리보기다
    month = client.get("/billing/summary", params={"month": "2026-10"}, headers=a).json()
    assert (month["total"], month["count"]) == (30000, 1)

    assert _settle(client, a, [e["id"]], "parents").status_code == 200
    s = _settlement(client, a)
    assert s["unsettled_count"] == 0
    bal = {b["name"]: b["balance"] for b in s["balances"]}
    assert bal == {"엄마": 30000, "지민": -15000, "수진": -15000}
    assert sum(bal.values()) == 0 and len(s["transfers"]) == 2


def test_only_settled_expenses_enter_the_balances(client, family):
    a, hdr, ids = _family(client, family)
    settled = _expense(client, hdr["지민"], 6000, "정산함")
    _expense(client, hdr["수진"], 99000, "아직")
    _settle(client, a, [settled["id"]], "all")
    s = _settlement(client, a)
    assert {b["name"]: b["paid"] for b in s["balances"]} == {"지민": 6000, "수진": 0, "엄마": 0}
    assert (s["unsettled_count"], s["unsettled_total"]) == (1, 99000)


def test_children_tag_without_minors_is_shared_by_adult_children(client, family):
    a, _, ids = _family(client, family)
    tags = _tags(client, a)
    assert set(tags["children"]["participants"]) == {ids["지민"], ids["수진"]}
    assert "성인 자녀" in tags["children"]["description"]


def test_children_tag_is_paid_by_parents_when_a_minor_child_exists(client, family):
    a, hdr, ids = _family(client, family)
    r = client.put("/billing/settlement/minors", json={"user_ids": [ids["수진"]]}, headers=a)
    assert r.status_code == 200 and r.json()["minor_ids"] == [ids["수진"]]
    tags = _tags(client, a)
    assert tags["children"]["participants"] == [ids["엄마"]]  # 미성년 자녀 몫은 부모님이 부담
    assert "부모님이 부담" in tags["children"]["description"]
    assert set(tags["parents"]["participants"]) == {ids["지민"], ids["수진"]}  # 다른 태그는 그대로
    assert set(tags["all"]["participants"]) == set(ids.values())

    e = _expense(client, hdr["지민"], 10000, "수진 학원비")  # 지민이 먼저 냄
    s = _settle(client, a, [e["id"]], "children").json()
    bal = {b["name"]: b["balance"] for b in s["balances"]}
    assert bal == {"지민": 10000, "수진": 0, "엄마": -10000}  # 엄마가 전부 부담
    assert s["transfers"][0]["from_name"] == "엄마"

    # 미성년 표시를 지우면 다시 성인 자녀끼리
    client.put("/billing/settlement/minors", json={"user_ids": []}, headers=a)
    assert set(_tags(client, a)["children"]["participants"]) == {ids["지민"], ids["수진"]}


def test_minor_marking_rules(client, family):
    a, hdr, ids = _family(client, family)
    # 부모 역할은 미성년으로 표시할 수 없다
    bad = client.put("/billing/settlement/minors", json={"user_ids": [ids["엄마"]]}, headers=a)
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_minor"
    assert (
        client.put(
            "/billing/settlement/minors", json={"user_ids": ["nobody"]}, headers=a
        ).status_code
        == 400
    )
    # 정산 담당자(기본: 그룹을 만든 지민)나 그룹을 만든 사람만 바꿀 수 있다
    denied = client.put(
        "/billing/settlement/minors", json={"user_ids": [ids["수진"]]}, headers=hdr["수진"]
    )
    assert denied.status_code == 403 and denied.json()["code"] == "not_manager"
    mgr = client.get("/billing/settlement/manager", headers=hdr["수진"]).json()
    assert mgr["minor_ids"] == []
    client.put("/billing/settlement/minors", json={"user_ids": [ids["수진"]]}, headers=a)
    assert client.get("/billing/settlement/manager", headers=hdr["수진"]).json()["minor_ids"] == [
        ids["수진"]
    ]
    # 담당자를 바꿔도 미성년 표시는 유지된다
    client.put("/billing/settlement/manager", json={"user_id": ids["엄마"]}, headers=a)
    assert client.get("/billing/settlement/manager", headers=a).json()["minor_ids"] == [ids["수진"]]


def test_children_tag_with_a_minor_but_no_parent_in_the_group_is_rejected(client, family):
    a, b, _ = family  # 부모 역할이 없는 가족
    ids = {
        m["name"]: m["id"]
        for m in client.get("/family-group/groups/me", headers=a).json()["members"]
    }
    client.put("/billing/settlement/minors", json={"user_ids": [ids["수진"]]}, headers=a)
    e = _expense(client, a, 3000)
    r = _settle(client, a, [e["id"]], "children")
    assert r.status_code == 400 and r.json()["code"] == "no_participants"
