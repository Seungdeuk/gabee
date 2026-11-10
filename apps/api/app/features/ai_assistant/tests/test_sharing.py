"""대화 내용 전달: 받는 사람 찾기, 확인 전에는 보내지 않기, 토큰, 경로 제한. 가짜 Claude 로 돈다."""

import pytest
from sqlalchemy import select

from app.features.ai_assistant import family_names, sharing
from app.features.ai_assistant.knowledge import rag_chat
from app.features.family_chat.models import Message
from app.features.family_group.models import GroupMember, MemberNickname
from app.shared.config import settings
from app.shared.db import SessionLocal
from tests.helpers import join_family, signup


@pytest.fixture
def clan(client, monkeypatch):
    """강민훈(소유자)·김영희(엄마)·강민수. AI 를 켠 가족."""
    me = signup(client, "강민훈", "parent")
    group = client.post("/family-group/groups", json={"name": "강씨네"}, headers=me).json()
    mom = signup(client, "김영희")
    brother = signup(client, "강민수")
    join_family(client, me, group["invite_code"], mom)
    join_family(client, me, group["invite_code"], brother)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    assert (
        client.put("/family-chat/ai/settings", json={"enabled": True}, headers=me).status_code
        == 200
    )
    with SessionLocal() as db:
        ids = {m.name: m.user_id for m in family_names.load_members(db, group["id"])}
        _relation(db, group["id"], ids["김영희"], "mom")
    return {"me": me, "mom": mom, "brother": brother, "gid": group["id"], "ids": ids}


def _relation(db, gid, uid, relation):
    row = db.scalar(
        select(GroupMember).where(GroupMember.group_id == gid, GroupMember.user_id == uid)
    )
    row.family_relation = relation
    db.commit()


def _text(text):
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "model": "m"}


def _call(args, name="prepare_share"):
    return {
        "content": [{"type": "tool_use", "id": "t1", "name": name, "input": args}],
        "stop_reason": "tool_use",
        "model": "m",
    }


def _chat(client, headers, monkeypatch, *replies, **body):
    script = iter(replies)
    bodies = []

    def post(request):
        bodies.append(request)
        return next(script)

    monkeypatch.setattr(rag_chat, "_post", post)
    res = client.post("/ai-assistant/chat", json={"message": "전해줘", **body}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json(), bodies


def _messages(gid):
    with SessionLocal() as db:
        return [m.text for m in db.scalars(select(Message).where(Message.group_id == gid))]


def test_card_first_then_sent_to_the_direct_room_under_my_name(client, clan, monkeypatch):
    out, bodies = _chat(
        client,
        clan["me"],
        monkeypatch,
        _call({"to": "엄마", "text": "주말 식당은 ○○로 생각 중이에요"}),
        _text("카드의 확인을 눌러 주세요."),
    )
    assert "prepare_share" in [t["name"] for t in bodies[0]["tools"]]
    card = out["proposals"][0]
    assert card["tab"] == "ai-assistant"
    assert card["summary"].startswith("김영희(엄마)에게 보낼까요?")
    assert _messages(clan["gid"]) == []  # 확인 전에는 아무것도 보내지 않는다

    done = client.post(
        "/ai-assistant/agent/confirm", json={"token": card["token"]}, headers=clan["me"]
    )
    assert done.status_code == 200
    with SessionLocal() as db:
        row = db.scalars(select(Message).where(Message.group_id == clan["gid"])).one()
        assert row.user_id == clan["ids"]["강민훈"]
        assert row.text == "주말 식당은 ○○로 생각 중이에요" + sharing.SIGNATURE
    rooms = client.get("/family-chat/rooms", headers=clan["mom"]).json()
    direct = next(r for r in rooms if r["kind"] == "direct")
    assert direct["peer_user_id"] == clan["ids"]["강민훈"]
    assert direct["unread"] == 1

    again = client.post(
        "/ai-assistant/agent/confirm", json={"token": card["token"]}, headers=clan["me"]
    )
    assert again.status_code == 409


def test_family_room_goes_to_everyone(client, clan, monkeypatch):
    out, _ = _chat(
        client,
        clan["me"],
        monkeypatch,
        _call({"to": "가족방", "text": "내일 모임 7시"}),
        _text("확인을 눌러 주세요."),
    )
    token = out["proposals"][0]["token"]
    assert out["proposals"][0]["summary"].startswith("가족 전체방에 보낼까요?")
    assert (
        client.post(
            "/ai-assistant/agent/confirm", json={"token": token}, headers=clan["me"]
        ).status_code
        == 200
    )
    with SessionLocal() as db:
        row = db.scalars(select(Message).where(Message.group_id == clan["gid"])).one()
        assert row.room_id is not None
    family = next(
        r
        for r in client.get("/family-chat/rooms", headers=clan["brother"]).json()
        if r["kind"] == "family"
    )
    assert family["unread"] == 1


def test_someone_else_cannot_use_my_token(client, clan, monkeypatch):
    out, _ = _chat(
        client, clan["me"], monkeypatch, _call({"to": "민수", "text": "안녕"}), _text("확인")
    )
    token = out["proposals"][0]["token"]
    res = client.post("/ai-assistant/agent/confirm", json={"token": token}, headers=clan["brother"])
    assert res.status_code == 400
    assert _messages(clan["gid"]) == []


def test_recipient_order_nickname_then_name_then_relation(clan):
    with SessionLocal() as db:
        db.add(
            MemberNickname(
                group_id=clan["gid"],
                owner_user_id=clan["ids"]["강민훈"],
                target_user_id=clan["ids"]["강민수"],
                nickname="엄마",  # 내가 동생을 '엄마'라고 저장했다면 별명이 먼저다
            )
        )
        db.commit()
        people = sharing._people(db, clan["gid"], clan["ids"]["강민훈"])
    assert [p.user_id for p in sharing.find_people(people, "엄마")] == [clan["ids"]["강민수"]]
    assert [p.user_id for p in sharing.find_people(people, "어머니")] == [clan["ids"]["김영희"]]
    assert [p.user_id for p in sharing.find_people(people, "민수")] == [clan["ids"]["강민수"]]
    assert [p.user_id for p in sharing.find_people(people, "민수 님")] == [clan["ids"]["강민수"]]
    assert sharing.find_people(people, "강민훈") == []  # 나에게는 보내지 않는다
    assert sharing.find_people(people, "") == []


def test_unknown_or_ambiguous_recipient_makes_no_card(client, clan, monkeypatch):
    with SessionLocal() as db:
        _relation(db, clan["gid"], clan["ids"]["강민수"], "mom")
    out, bodies = _chat(
        client,
        clan["me"],
        monkeypatch,
        _call({"to": "엄마", "text": "안녕"}),
        _text("어느 분이요?"),
    )
    assert out["proposals"] == []
    result = bodies[1]["messages"][-1]["content"][0]["content"]
    assert "need_recipient" in result and "김영희(엄마)" in result and "강민수(엄마)" in result

    out, bodies = _chat(
        client, clan["me"], monkeypatch, _call({"to": "삼촌", "text": "안녕"}), _text("누구요?")
    )
    assert out["proposals"] == []
    assert "need_recipient" in bodies[1]["messages"][-1]["content"][0]["content"]

    out, _ = _chat(
        client,
        clan["me"],
        monkeypatch,
        _call({"to": "엄마", "text": "안녕", "member_id": clan["ids"]["김영희"]}),
        _text("확인"),
    )
    assert out["proposals"][0]["summary"].startswith("김영희(엄마)에게")


@pytest.mark.parametrize(
    "args",
    [
        {"to": "민수", "text": ""},
        {"to": "민수", "text": "가" * 501},
        {"to": "민수", "text": "주민번호 900101-1234567"},
        {"to": "민수", "text": "안녕", "member_id": "outsider"},
    ],
)
def test_bad_share_is_refused(client, clan, monkeypatch, args):
    out, bodies = _chat(client, clan["me"], monkeypatch, _call(args), _text("못 보내요"))
    assert out["proposals"] == []
    assert bodies[1]["messages"][-1]["content"][0]["is_error"] is True


def test_long_share_token_is_accepted(client, clan, monkeypatch):
    out, _ = _chat(
        client, clan["me"], monkeypatch, _call({"to": "민수", "text": "가" * 500}), _text("확인")
    )
    token = out["proposals"][0]["token"]
    assert (
        client.post(
            "/ai-assistant/agent/confirm", json={"token": token}, headers=clan["me"]
        ).status_code
        == 200
    )


def test_recipient_who_left_gets_nothing(client, clan, monkeypatch):
    out, _ = _chat(
        client, clan["me"], monkeypatch, _call({"to": "민수", "text": "안녕"}), _text("확인")
    )
    token = out["proposals"][0]["token"]
    assert client.post("/family-group/groups/me/leave", headers=clan["brother"]).status_code in (
        200,
        204,
    )
    res = client.post("/ai-assistant/agent/confirm", json={"token": token}, headers=clan["me"])
    assert res.status_code == 400
    assert _messages(clan["gid"]) == []


def test_family_room_mention_has_no_share_tool(client, clan, monkeypatch):
    _, bodies = _chat(client, clan["me"], monkeypatch, _text("답"), audience="room")
    assert "prepare_share" not in [t["name"] for t in bodies[0]["tools"]]


def test_no_share_tool_when_family_ai_is_off(client, clan):
    from app.shared import ai_guard

    with SessionLocal() as db:
        assert ai_guard.is_enabled(db, clan["gid"]) is True
    assert (
        client.put(
            "/family-chat/ai/settings", json={"enabled": False}, headers=clan["me"]
        ).status_code
        == 200
    )
    with SessionLocal() as db:
        seen = []

        def post(body):
            seen.append(body)
            return _text("답")

        rag_chat.ask(db, clan["gid"], "안녕", post=post, personal=True)
    assert "prepare_share" not in [t["name"] for t in seen[0]["tools"]]


def test_after_someone_left_the_direct_room_a_new_room_is_used(client, clan, monkeypatch):
    def send():
        out, _ = _chat(
            client, clan["me"], monkeypatch, _call({"to": "민수", "text": "안녕"}), _text("확인")
        )
        token = out["proposals"][0]["token"]
        res = client.post("/ai-assistant/agent/confirm", json={"token": token}, headers=clan["me"])
        assert res.status_code == 200

    send()
    rooms = client.get("/family-chat/rooms", headers=clan["brother"]).json()
    old = next(r for r in rooms if r["kind"] == "direct")["id"]
    assert client.post(f"/family-chat/rooms/{old}/leave", headers=clan["brother"]).status_code in (
        200,
        204,
    )
    send()
    rooms = client.get("/family-chat/rooms", headers=clan["brother"]).json()
    new = next(r for r in rooms if r["kind"] == "direct")
    assert new["id"] != old and new["unread"] == 1
