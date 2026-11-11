"""문의·신고 보내기와 내 문의 보기: 본인 것만 보이고, 사용자가 쓴 글만 저장한다."""

from tests.helpers import signup

TICKETS = "/support/tickets"
MINE = "/support/tickets/mine"


def test_requires_login(client):
    assert (
        client.post(TICKETS, json={"kind": "inquiry", "title": "a", "body": "b"}).status_code == 401
    )
    assert client.get(MINE).status_code == 401


def test_send_and_see_my_tickets(client, family):
    a, _, group = family
    r = client.post(
        TICKETS,
        json={
            "kind": "report",
            "title": "  광고 메시지를 받았어요 ",
            "body": "모르는 링크가 왔어요",
        },
        headers=a,
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert (t["kind"], t["title"], t["status"]) == ("report", "광고 메시지를 받았어요", "new")
    assert t["answer"] is None and t["answered_at"] is None

    client.post(
        TICKETS, json={"kind": "inquiry", "title": "탈퇴", "body": "사진도 지워지나요?"}, headers=a
    )
    rows = client.get(MINE, headers=a).json()["rows"]
    assert [x["title"] for x in rows] == ["탈퇴", "광고 메시지를 받았어요"]  # 최근순

    from app.features.support.models import SupportTicket
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        assert db.get(SupportTicket, t["id"]).group_id == group["id"]  # 보낼 때의 가족을 남긴다


def test_others_tickets_are_not_visible(client, family):
    a, b, _ = family
    client.post(TICKETS, json={"kind": "inquiry", "title": "내 문의", "body": "내용"}, headers=a)
    assert client.get(MINE, headers=b).json()["rows"] == []


def test_user_without_family_can_send(client):
    h = signup(client, "민수")
    r = client.post(
        TICKETS, json={"kind": "inquiry", "title": "가족 만들기", "body": "어떻게 해요?"}, headers=h
    )
    assert r.status_code == 201, r.text


def test_invalid_input_is_rejected(client, family):
    a, _, _ = family
    for body in (
        {"kind": "chat", "title": "a", "body": "b"},  # 없는 종류
        {"kind": "inquiry", "title": "", "body": "b"},
        {"kind": "inquiry", "title": "a", "body": ""},
        {"kind": "inquiry", "title": "가" * 101, "body": "b"},
        {"kind": "inquiry", "title": "a", "body": "가" * 2001},
    ):
        assert client.post(TICKETS, json=body, headers=a).status_code == 422, body
    assert client.get(MINE, headers=a).json()["rows"] == []
