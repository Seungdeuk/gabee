"""w2 의 정산 시드: w1 의 `evals/tab_agents/seed.py`(기존 정산 시드)와 같은 순서·구조로 w2 값(`data_w2`)을 앱의 공개 API 로 만든다.

기존 정산 시드 파일은 바꾸지 않는다(dev 월드·기존 52건의 기대값이 그대로여야 한다). 이 모듈은 val 월드 전용이다.
"""

from fastapi.testclient import TestClient

from . import data_w2 as d


def _post(client: TestClient, path: str, body: dict, headers: dict, ok=(201,)) -> dict:
    r = client.post(path, json=body, headers=headers)
    assert r.status_code in ok, f"{path} {r.status_code} {r.text}"
    return r.json()


def _expense(client: TestClient, e: d.BillingExpense, headers: dict) -> dict:
    return _post(
        client,
        "/billing/expenses",
        {"title": e.title, "amount": e.amount, "date": e.day},
        headers,
    )


def seed(client: TestClient, a: dict, b: dict) -> None:
    """a=지민, b=수진 헤더. 2026-10·2026-11 지출, 구독 하나, 제목 속 지시문 두 건."""
    who = {"지민": a, "수진": b}
    for e in d.OCTOBER:
        _expense(client, e, who[e.payer])
    client.post("/billing/subscriptions", json=d.SUBSCRIPTION, headers=a)
    for e in d.NOVEMBER:
        _expense(client, e, who[e.payer])
    _expense(client, d.POISONED_SEPTEMBER, a)
    _expense(client, d.POISONED_AUGUST, a)


def seed_child(client: TestClient, owner: dict, child_id: str) -> None:
    """자녀(민수)의 용돈 주기와 입금. 주기 설정은 그룹을 만든 사람(owner)만 할 수 있다."""
    r = client.put(f"/billing/allowances/{child_id}/plan", json=d.ALLOWANCE_PLAN, headers=owner)
    assert r.status_code == 200, r.text
    _post(client, f"/billing/allowances/{child_id}/credits", d.ALLOWANCE_CREDIT, owner, (200, 201))


def seed_other_family(client: TestClient, other: dict) -> None:
    """다른 가족의 데이터. 어떤 질문으로도 우리 가족 답에 나오면 안 된다."""
    client.post("/family-group/groups", json={"name": d.OTHER_FAMILY_NAME}, headers=other)
    _expense(client, d.OTHER_FAMILY_EXPENSE, other)


def seed_write_targets(client: TestClient, a: dict, b: dict, child: dict | None = None) -> None:
    """2026-06 정산 전 지출 두 건, 2026-07 정산하기까지 마친 지출. child 헤더를 주면 민수의 용돈 요청도 만든다."""
    who = {"지민": a, "수진": b}
    for e in d.JUNE:
        _expense(client, e, who[e.payer])
    for e in d.JULY:
        made = _expense(client, e, who[e.payer])
        if e.settle:
            _post(
                client,
                "/billing/settlement/tag",
                {"month": e.day[:7], "expense_ids": [made["id"]], "tag": "all"},
                a,
                (200, 201),
            )
    if child is not None:
        members = client.get("/family-group/groups/me", headers=a).json()["members"]
        child_id = next(m["id"] for m in members if m["name"] == "민수")
        _post(
            client,
            f"/billing/allowances/{child_id}/requests",
            d.ALLOWANCE_REQUEST,
            child,
            (200, 201),
        )
