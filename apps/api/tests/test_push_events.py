"""알림함 사건 연결(푸시 PR 1): 새 공유 일정·할 일 배정·정산·송금 완료·용돈 요청이 고정 문구로 남고, 본인과 대상 아닌 사람은 받지 않는다."""

from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select

from app.shared.db import SessionLocal
from app.shared.notifications import Notification
from tests.helpers import join_family, signup

MONTH = "2026-10"


@pytest.fixture
def home(client, family):
    """지민(그룹을 만든 사람)·수진(자녀). 가입 알림은 지우고 시작한다(알림 개수를 직접 센다)."""
    with SessionLocal() as db:
        db.execute(delete(Notification))
        db.commit()
    return family


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _rows(user_id: str, event: str | None = None) -> list[Notification]:
    with SessionLocal() as db:
        q = select(Notification).where(Notification.user_id == user_id)
        if event:
            q = q.where(Notification.event == event)
        return list(db.scalars(q))


def _soon() -> str:
    return (date.today() + timedelta(days=3)).isoformat() + "T10:00:00+09:00"


# ── 일정 ────────────────────────────────────────────────


def test_new_shared_event_notifies_only_the_people_it_is_shared_with(client, home):
    a, b, _ = home
    a_id, b_id = _me(client, a), _me(client, b)
    r = client.post(
        "/schedule/events",
        json={"title": "병원 진료 박OO", "starts_at": _soon(), "share_with": [b_id]},
        headers=a,
    )
    assert r.status_code == 201, r.text
    got = _rows(b_id, "event_shared")
    assert len(got) == 1
    n = got[0]
    assert n.kind == "schedule" and n.title == "가족이 일정을 공유했어요"
    assert n.actor_user_id == a_id
    assert "병원" not in (n.title + (n.body or ""))  # 제목·내용을 문구에 담지 않는다
    assert _rows(a_id, "event_shared") == []  # 만든 사람은 받지 않는다


def test_event_without_sharing_sends_nothing(client, home):
    a, b, _ = home
    client.post("/schedule/events", json={"title": "혼자 일정", "starts_at": _soon()}, headers=a)
    assert _rows(_me(client, b), "event_shared") == []


def test_adding_a_person_to_an_existing_share_notifies_only_the_new_person(client, home):
    a, b, group = home
    c = signup(client, "삼촌")
    assert join_family(client, a, group["invite_code"], c).status_code == 200
    with SessionLocal() as db:
        db.execute(delete(Notification))
        db.commit()
    b_id, c_id = _me(client, b), _me(client, c)
    ev = client.post(
        "/schedule/events",
        json={"title": "가족 모임", "starts_at": _soon(), "share_with": [b_id]},
        headers=a,
    ).json()
    client.patch(f"/schedule/events/{ev['id']}", json={"share_with": [b_id, c_id]}, headers=a)
    assert len(_rows(b_id, "event_shared")) == 1  # 이미 받은 사람에게는 다시 가지 않는다
    assert len(_rows(c_id, "event_shared")) == 1


# ── 할 일 배정 ──────────────────────────────────────────


def test_todo_assignment_notifies_the_assignee_only(client, home):
    a, b, _ = home
    a_id, b_id = _me(client, a), _me(client, b)
    r = client.post(
        "/family-chat/todos", json={"title": "우유 사 오기", "assignee_id": b_id}, headers=a
    )
    assert r.status_code == 201, r.text
    got = _rows(b_id, "todo_assigned")
    assert len(got) == 1 and got[0].title == "할 일이 배정됐어요" and got[0].kind == "schedule"
    assert "우유" not in got[0].title
    assert _rows(a_id, "todo_assigned") == []


def test_todo_assigned_to_myself_or_nobody_sends_nothing(client, home):
    a, b, _ = home
    client.post(
        "/family-chat/todos", json={"title": "내 할 일", "assignee_id": _me(client, a)}, headers=a
    )
    client.post("/family-chat/todos", json={"title": "아무나"}, headers=a)
    assert _rows(_me(client, a)) == [] and _rows(_me(client, b)) == []


def test_changing_the_assignee_notifies_the_new_assignee_but_not_on_other_edits(client, home):
    a, b, _ = home
    b_id = _me(client, b)
    todo = client.post("/family-chat/todos", json={"title": "청소"}, headers=a).json()
    client.patch(f"/family-chat/todos/{todo['id']}", json={"assignee_id": b_id}, headers=a)
    assert len(_rows(b_id, "todo_assigned")) == 1
    client.patch(f"/family-chat/todos/{todo['id']}", json={"title": "청소 하기"}, headers=a)
    client.patch(
        f"/family-chat/todos/{todo['id']}", json={"assignee_id": b_id}, headers=a
    )  # 같은 사람
    assert len(_rows(b_id, "todo_assigned")) == 1


# ── 지갑(정산·송금·용돈) ────────────────────────────────


def _owe_sujin(client, a, b):
    """지민이 낸 지출을 둘이 나누는 정산하기까지 한 상태(수진이 지민에게 보낼 돈이 생긴다)."""
    e = client.post(
        "/billing/expenses",
        json={"title": "장보기", "amount": 10000, "date": "2026-10-12"},
        headers=a,
    ).json()
    r = client.post(
        "/billing/settlement/tag",
        json={"month": MONTH, "expense_ids": [e["id"]], "tag": "all"},
        headers=a,
    )
    assert r.status_code == 200, r.text


def test_settling_notifies_the_participants_except_the_actor(client, home):
    a, b, _ = home
    _owe_sujin(client, a, b)
    got = _rows(_me(client, b), "settlement_updated")
    assert len(got) == 1 and got[0].kind == "billing"
    assert got[0].title == "정산 내역이 업데이트됐어요"
    assert "10000" not in (got[0].title + (got[0].body or ""))  # 금액을 담지 않는다
    assert _rows(_me(client, a), "settlement_updated") == []


def test_settling_also_notifies_the_person_who_paid_the_expense(client, home):
    """지출을 낸 사람이 나눌 사람에 없어도(예: 부모 제외 태그) 잔액이 바뀌므로 알림을 받는다."""
    a, b, _ = home
    e = client.post(
        "/billing/expenses",
        json={"title": "장보기", "amount": 10000, "date": "2026-10-12"},
        headers=b,
    ).json()
    r = client.post(
        "/billing/settlement/tag",
        json={
            "month": MONTH,
            "expense_ids": [e["id"]],
            "tag": "custom",
            "participants": [_me(client, a)],
        },
        headers=a,
    )
    assert r.status_code == 200, r.text
    assert len(_rows(_me(client, b), "settlement_updated")) == 1  # 낸 사람(수진, 나눌 사람 아님)
    assert _rows(_me(client, a), "settlement_updated") == []  # 정산한 본인


def test_marking_a_payment_notifies_the_other_side(client, home):
    a, b, _ = home
    _owe_sujin(client, a, b)
    t = client.get("/billing/settlement", params={"month": MONTH}, headers=a).json()["transfers"][0]
    client.post(
        "/billing/settlement/payments",
        json={
            "month": MONTH,
            "from_user_id": t["from_user_id"],
            "to_user_id": t["to_user_id"],
            "amount": t["amount"],
        },
        headers=a,
    )
    receivers = [t["from_user_id"], t["to_user_id"]]
    got = [r for uid in receivers for r in _rows(uid, "payment_marked")]
    assert len(got) == 1  # 표시한 사람(지민)은 빠지고 상대 한 명만
    assert got[0].title == "송금 완료가 표시됐어요" and got[0].user_id == _me(client, b)


def test_allowance_request_notifies_the_managers_and_the_decision_notifies_the_child(client, home):
    a, b, group = home
    mom = signup(client, "엄마", role="parent")
    assert join_family(client, a, group["invite_code"], mom).status_code == 200
    with SessionLocal() as db:
        db.execute(delete(Notification))
        db.commit()
    a_id, b_id, mom_id = _me(client, a), _me(client, b), _me(client, mom)
    r = client.post(
        f"/billing/allowances/{b_id}/requests", json={"amount": 5000, "memo": "학용품"}, headers=b
    )
    assert r.status_code == 201, r.text
    assert len(_rows(a_id, "allowance_requested")) == 1  # 그룹을 만든 사람
    assert len(_rows(mom_id, "allowance_requested")) == 1  # 부모
    assert _rows(b_id, "allowance_requested") == []  # 요청한 본인
    assert _rows(a_id, "allowance_requested")[0].title == "용돈 요청이 도착했어요"
    request_id = r.json()["requests"][0]["id"]
    ok = client_post_decide(client, mom, b_id, request_id, "approve")
    assert ok.status_code == 200, ok.text
    done = _rows(b_id, "allowance_decided")
    assert (
        len(done) == 1 and done[0].title == "용돈 요청이 처리됐어요"
    )  # 승인·거절 여부는 담지 않는다
    assert "5000" not in done[0].title


def client_post_decide(client, headers, child_id, request_id, action):
    return client.post(
        f"/billing/allowances/{child_id}/requests/{request_id}/{action}", json={}, headers=headers
    )
