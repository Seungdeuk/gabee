"""소통 푸시(2단계): 새 글·사진·파일이 올라오면 받을 사람에게 고정 문구 푸시만 간다(알림함에는 남기지 않는다).
내용·보낸 사람·방 이름은 담지 않고, 보낸 사람·방 알림을 끈 사람은 받지 않으며, 같은 묶음 사진과 연달아 보낸 글은 한 번만 보낸다."""

import io
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import select

from app.features.family_chat import chat_push, photo_service
from app.features.family_chat.models import Message
from app.shared import push
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.notifications import Notification
from app.shared.push_models import PushToken
from tests.helpers import join_family, signup

TITLE = "새 메시지가 도착했어요"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    photo_service.upload_limiter._failures.clear()


@pytest.fixture
def sent(monkeypatch):
    """발송을 켜고, 스레드 대신 그 자리에서 실행하고, Expo 호출을 가짜로 바꾼다. 보낸 푸시 목록을 돌려준다."""
    batches: list[list[dict]] = []

    def fake_post(messages):
        batches.append(messages)
        return {"data": [{"status": "ok", "id": f"t{i}"} for i, _ in enumerate(messages)]}

    monkeypatch.setattr(settings, "push_enabled", True)
    monkeypatch.setattr(push, "_submit", lambda fn, *args: fn(*args))
    monkeypatch.setattr(push, "_post", fake_post)
    return lambda: [m for batch in batches for m in batch]


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _token(user_id: str, token: str) -> None:
    with SessionLocal() as db:
        db.add(PushToken(user_id=user_id, token=token, platform="android"))
        db.commit()


@pytest.fixture
def trio(client, family):
    """지민(a)·수진(b)·삼촌(c) 모두 푸시 토큰을 갖고 있다. 토큰 이름은 사용자 이름 첫 글자."""
    a, b, group = family
    c = signup(client, "삼촌")
    assert join_family(client, a, group["invite_code"], c).status_code == 200
    for name, headers in (("a", a), ("b", b), ("c", c)):
        _token(_me(client, headers), f"ExponentPushToken[{name}]")
    return a, b, c


def _say(client, headers, text="안녕하세요 비밀 내용", room_id=None):
    body = {"text": text}
    if room_id:
        body["room_id"] = room_id
    r = client.post("/family-chat/messages", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    return out.getvalue()


def _photo(client, headers, batch_id=None, room_id=None):
    data = {}
    if batch_id:
        data["batch_id"] = batch_id
    if room_id:
        data["room_id"] = room_id
    r = client.post(
        "/family-chat/photos",
        files={"file": ("a.jpg", _jpeg(), "image/jpeg")},
        data=data or None,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _tokens(pushes):
    return sorted(m["to"] for m in pushes)


def test_new_message_pushes_a_fixed_text_to_everyone_but_the_sender(client, trio, sent):
    a, b, c = trio
    _say(client, a)
    pushes = sent()
    assert _tokens(pushes) == [
        "ExponentPushToken[b]",
        "ExponentPushToken[c]",
    ]  # 보낸 사람(a)은 빠진다
    for m in pushes:
        assert m["title"] == TITLE and not m.get("body")
        assert m["data"]["kind"] == "chat" and m["data"]["room_id"]
        assert "비밀" not in str(m)  # 글 내용이 어디에도 실리지 않는다
        assert "지민" not in str(m)  # 보낸 사람 이름도 싣지 않는다
        # 같은 방의 푸시는 잠금 화면에서 한 건으로 교체된다(안드로이드 tag, iOS collapseId = 방 id)
        assert m["tag"] == m["collapseId"] == m["data"]["room_id"]


def test_chat_push_is_not_stored_in_the_notification_box(client, trio, sent):
    a, _, _ = trio
    _say(client, a)
    with SessionLocal() as db:
        assert db.scalars(select(Notification).where(Notification.kind == "chat")).all() == []


def test_direct_room_message_goes_only_to_the_other_participant(client, trio, sent):
    a, b, c = trio
    room = client.post(
        "/family-chat/rooms/direct", json={"user_id": _me(client, b)}, headers=a
    ).json()
    _say(client, a, room_id=room["id"])
    pushes = sent()
    assert _tokens(pushes) == ["ExponentPushToken[b]"]  # 삼촌(c)은 1:1 방 참가자가 아니다
    assert pushes[0]["data"] == {
        "kind": "chat",
        "room_id": room["id"],
    }  # 보낸 사람 id 등 다른 값은 싣지 않는다


def test_people_who_muted_the_room_do_not_get_a_push(client, trio, sent):
    a, b, c = trio
    rooms = client.get("/family-chat/rooms", headers=b).json()
    family_room = next(r for r in rooms if r["kind"] == "family")
    assert (
        client.put(
            f"/family-chat/rooms/{family_room['id']}/mute", json={"muted": True}, headers=b
        ).status_code
        == 200
    )
    _say(client, a)
    assert _tokens(sent()) == ["ExponentPushToken[c]"]


def test_user_can_mute_the_chat_push_kind(client, trio, sent):
    a, b, c = trio
    r = client.put("/notifications/push-settings", json={"muted_kinds": ["chat"]}, headers=c)
    assert r.status_code == 200, r.text
    _say(client, a)
    assert _tokens(sent()) == ["ExponentPushToken[b]"]


def test_quick_follow_up_messages_from_the_same_sender_push_once(client, trio, sent, monkeypatch):
    a, b, c = trio
    monkeypatch.setattr(
        chat_push, "window_start", lambda at: datetime.now(UTC) - timedelta(seconds=60)
    )  # 시험 중 10초 칸 경계를 넘어 flaky 해지지 않게 창 시작을 고정
    _say(client, a, "하나")
    _say(client, a, "둘")
    _say(client, a, "셋")
    assert len(sent()) == 2  # b, c 에게 한 번씩만(첫 글에서)


def test_another_sender_still_pushes_during_a_burst(client, trio, sent, monkeypatch):
    a, b, c = trio
    monkeypatch.setattr(
        chat_push, "window_start", lambda at: datetime.now(UTC) - timedelta(seconds=60)
    )
    _say(client, a, "하나")
    _say(client, b, "답장")
    assert _tokens(sent()) == [
        "ExponentPushToken[a]",  # 답장(b → a, c)
        "ExponentPushToken[b]",  # 첫 글(a → b, c)
        "ExponentPushToken[c]",
        "ExponentPushToken[c]",
    ]


def test_photos_of_one_batch_push_once_even_when_spread_over_time(client, trio, sent, monkeypatch):
    a, b, c = trio
    monkeypatch.setattr(chat_push, "BURST_SECONDS", 0)  # 시간 간격 규칙을 꺼도 묶음 번호로 한 번만
    for _ in range(3):
        _photo(client, a, batch_id="batch0001abc")
    assert _tokens(sent()) == ["ExponentPushToken[b]", "ExponentPushToken[c]"]
    _photo(client, a, batch_id="batch0002abc")  # 새 묶음은 다시 한 번
    assert len(sent()) == 4


def test_single_photo_and_file_push_the_same_fixed_text(client, trio, sent, monkeypatch):
    a, b, c = trio
    monkeypatch.setattr(chat_push, "BURST_SECONDS", 0)
    _photo(client, a)
    r = client.post(
        "/family-chat/files", files={"file": ("메모.txt", b"hello", "text/plain")}, headers=a
    )
    assert r.status_code == 201, r.text
    pushes = sent()
    assert len(pushes) == 4  # 사진 1건 + 파일 1건, 각각 b·c
    assert all(m["title"] == TITLE and not m.get("body") for m in pushes)
    assert all("메모" not in str(m) for m in pushes)  # 파일 이름도 싣지 않는다


def test_nothing_is_sent_when_push_is_disabled(client, trio, monkeypatch):
    calls = []
    monkeypatch.setattr(push, "_submit", lambda fn, *args: calls.append(args))
    a, _, _ = trio
    _say(client, a)  # PUSH_ENABLED 는 기본 꺼짐
    assert calls == []


def test_a_new_window_pushes_again_even_while_the_conversation_goes_on(client, trio, sent):
    """10초 칸이 바뀌면 다시 푸시한다(슬라이딩 창이면 대화가 이어지는 동안 첫 글 뒤로는 영영 푸시가 없다)."""
    a, b, c = trio
    first = _say(client, a, "하나")
    with SessionLocal() as db:  # 첫 글을 1분 전 글로 돌린다(지난 칸)
        row = db.get(Message, first["id"])
        row.created_at = datetime.now(UTC) - timedelta(seconds=60)
        db.commit()
    _say(client, a, "둘")
    assert len(sent()) == 4  # 첫 글 b·c, 지난 칸 뒤 새 글 b·c


def test_member_who_left_the_family_gets_no_direct_room_push(client, trio, sent):
    a, b, c = trio
    room = client.post(
        "/family-chat/rooms/direct", json={"user_id": _me(client, c)}, headers=a
    ).json()
    assert client.post("/family-group/groups/me/leave", headers=c).status_code == 204
    _say(client, a, room_id=room["id"])  # 1:1 방 참여 기록은 남아 있어도 가족이 아니면 받지 않는다
    assert sent() == []


def test_a_push_failure_never_breaks_sending_the_message(client, trio, sent, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("push down")

    monkeypatch.setattr(chat_push, "push_only", boom)
    a, _, _ = trio
    r = client.post("/family-chat/messages", json={"text": "푸시가 죽어도"}, headers=a)
    assert r.status_code == 201  # 메시지는 정상 전송


def test_batch_photo_check_only_looks_at_recent_photos(client, trio, sent, monkeypatch):
    """같은 번호를 오래 뒤에 다시 쓰면(클라이언트 실수) 영영 푸시가 막히지 않는다."""
    a, b, c = trio
    monkeypatch.setattr(chat_push, "BURST_SECONDS", 0)
    first = _photo(client, a, batch_id="batchold0001")
    with SessionLocal() as db:
        row = db.get(Message, first["id"])
        row.created_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
    _photo(client, a, batch_id="batchold0001")
    assert len(sent()) == 4  # 오래된 번호는 새 묶음으로 본다
