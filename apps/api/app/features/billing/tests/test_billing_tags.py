"""정산하기: 대상 태그(고정 3개 + 직접 고르기)로 나눌 사람을 정하고 기존 잔액·송금 계산을 그대로 쓴다."""

from tests.helpers import signup


def _family(client, family):
    """엄마(parent) 추가: 지민·수진(child) + 엄마. 구성원 id 를 이름으로 돌려준다."""
    a, b, group = family
    mom = signup(client, "엄마", role="parent")
    client.post("/family-group/groups/join", json={"code": group["invite_code"]}, headers=mom)
    members = client.get("/family-group/groups/me", headers=a).json()["members"]
    ids = {m["name"]: m["id"] for m in members}
    return a, {"지민": a, "수진": b, "엄마": mom}, ids


def _expense(client, headers, amount, **extra):
    """낸 사람은 요청한 사람(headers)이다."""
    body = {"title": "병원비", "amount": amount, "date": "2026-10-12", **extra}
    r = client.post("/billing/expenses", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _settle(client, headers, ids, tag, participants=None):
    body = {"month": "2026-10", "expense_ids": ids, "tag": tag}
    if participants is not None:
        body["participants"] = participants
    return client.post("/billing/settlement/tag", json=body, headers=headers)


def test_fixed_tags_fill_participants_by_role(client, family):
    a, hdr, ids = _family(client, family)
    tags = {t["key"]: t for t in client.get("/billing/settlement/tags", headers=a).json()}
    assert set(tags) == {"parents", "children", "all"}
    assert set(tags["parents"]["participants"]) == {ids["지민"], ids["수진"]}  # 자녀들이 부담
    assert set(tags["children"]["participants"]) == {ids["지민"], ids["수진"]}
    assert set(tags["all"]["participants"]) == set(ids.values())
    assert all(t["label"] for t in tags.values())


def test_settle_with_fixed_tag_keeps_balances_summing_to_zero(client, family):
    a, hdr, ids = _family(client, family)
    e = _expense(client, hdr["엄마"], 30001)  # 엄마가 낸 부모님 병원비
    assert e["target_tag"] == "all"  # 정산하기 전에는 기본 가족 전체
    r = _settle(client, a, [e["id"]], "parents")
    assert r.status_code == 200, r.text
    s = r.json()
    bal = {b["name"]: b["balance"] for b in s["balances"]}
    assert sum(bal.values()) == 0
    assert (
        bal["엄마"] == 30001 and bal["지민"] == -15001 and bal["수진"] == -15000
    )  # 나머지 1원은 앞 사람
    assert {t["to_name"] for t in s["transfers"]} == {"엄마"}
    listed = client.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json()
    assert listed[0]["target_tag"] == "parents" and set(listed[0]["split_among"]) == {
        ids["지민"],
        ids["수진"],
    }


def test_custom_mode_uses_the_chosen_people(client, family):
    a, hdr, ids = _family(client, family)
    e = _expense(client, hdr["수진"], 9000)
    r = _settle(client, a, [e["id"]], "custom", [ids["지민"], ids["엄마"]])
    s = r.json()
    bal = {b["name"]: b["balance"] for b in s["balances"]}
    assert (bal["수진"], bal["지민"], bal["엄마"]) == (9000, -4500, -4500)
    assert (
        client.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json()[0][
            "target_tag"
        ]
        == "custom"
    )


def test_fixed_tag_ignores_sent_participants_and_each_expense_can_differ(client, family):
    a, hdr, ids = _family(client, family)
    e1 = _expense(client, hdr["엄마"], 3000)
    e2 = _expense(client, hdr["지민"], 6000)
    _settle(client, a, [e1["id"]], "parents", [ids["엄마"]])  # 고정 태그는 보낸 사람 목록을 무시
    _settle(client, a, [e2["id"]], "all")
    by_title = {
        x["id"]: x
        for x in client.get("/billing/expenses", params={"month": "2026-10"}, headers=a).json()
    }
    assert set(by_title[e1["id"]]["split_among"]) == {ids["지민"], ids["수진"]}
    assert (
        by_title[e1["id"]]["target_tag"] == "parents" and by_title[e2["id"]]["target_tag"] == "all"
    )


def test_settle_rejects_bad_input(client, family):
    a, hdr, ids = _family(client, family)
    e = _expense(client, hdr["지민"], 3000)
    assert _settle(client, a, [e["id"]], "custom", []).json()["code"] == "empty_split"
    assert _settle(client, a, [e["id"]], "custom").json()["code"] == "empty_split"
    assert _settle(client, a, [e["id"]], "custom", ["nobody"]).json()["code"] == "invalid_split"
    assert _settle(client, a, ["nope"], "all").json()["code"] == "unknown_expense"
    assert _settle(client, a, [e["id"]], "bogus").status_code == 422
    other_month = {"month": "2026-09", "expense_ids": [e["id"]], "tag": "all"}
    assert (
        client.post("/billing/settlement/tag", json=other_month, headers=a).json()["code"]
        == "unknown_expense"
    )
    # 삭제한 지출은 정산할 수 없다
    client.delete(f"/billing/expenses/{e['id']}", headers=a)
    assert _settle(client, a, [e["id"]], "all").json()["code"] == "unknown_expense"


def test_settle_is_locked_after_a_payment_is_marked(client, family):
    a, hdr, ids = _family(client, family)
    e = _expense(client, hdr["엄마"], 6000)
    s = _settle(client, a, [e["id"]], "all").json()
    t = s["transfers"][0]
    paid = client.post(
        "/billing/settlement/payments",
        json={
            "month": "2026-10",
            "from_user_id": t["from_user_id"],
            "to_user_id": t["to_user_id"],
            "amount": t["amount"],
        },
        headers=a,
    ).json()
    assert _settle(client, a, [e["id"]], "parents").json()["code"] == "settlement_locked"
    client.delete(f"/billing/settlement/payments/{paid['completed'][0]['id']}", headers=a)
    assert _settle(client, a, [e["id"]], "parents").status_code == 200


def test_expense_created_with_a_subset_is_marked_custom(client, family):
    a, hdr, ids = _family(client, family)
    e = _expense(client, hdr["지민"], 4000, split_among=[ids["지민"], ids["수진"]])
    assert e["target_tag"] == "custom"
    full = _expense(client, hdr["지민"], 4000, split_among=list(ids.values()))
    assert full["target_tag"] == "all"
