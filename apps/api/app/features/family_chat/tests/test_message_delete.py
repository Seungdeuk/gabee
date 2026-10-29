"""메시지 삭제: 내가 보낸 것만, 소프트 삭제(본문·사진을 서버에서도 지움), 방 격리, 삭제된 내용은 조회·검색·AI·사진 모음에 나오지 않는다."""

import io
from pathlib import Path

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.features.family_chat import ai_repository
from app.features.family_chat.assistant import get_or_create_assistant
from app.features.family_chat.models import ASSISTANT_USER_ID, Message, MessageAttachment
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

MSG = "/family-chat/messages"
PHOTOS = "/family-chat/photos"
MEDIA = "/family-chat/media"
SEARCH = "/family-chat/search"
ROOMS = "/family-chat/rooms"
DIRECT_ROOM = "/family-chat/rooms/direct"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """사진은 임시 폴더에 저장하고, 삭제는 AI 를 부르지 않는다."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)


@pytest.fixture
def trio(client, family):
    a, b, group = family
    c = signup(client, "삼촌")
    assert join_family(client, a, group["invite_code"], c).status_code == 200
    return a, b, c


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def _send(client, headers, text, room_id=None):
    body = {"text": text} if room_id is None else {"text": text, "room_id": room_id}
    r = client.post(MSG, json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _photo(client, headers):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    r = client.post(
        PHOTOS, files={"file": ("a.jpg", out.getvalue(), "image/jpeg")}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


def _delete(client, headers, message_id, room_id=None):
    params = {"room_id": room_id} if room_id else None
    return client.delete(f"{MSG}/{message_id}", params=params, headers=headers)


def _messages(client, headers, **params):
    r = client.get(MSG, params={"latest": True, **params}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_author_deletes_own_message_and_text_is_cleared(client, family):
    a, b, _ = family
    mid = _send(client, a, "비밀번호는 1234야")
    r = _delete(client, a, mid)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == mid and r.json()["deleted"] is True
    assert r.json()["text"] == "" and r.json()["attachment"] is None
    # 상대방 화면에도 같은 자리에 삭제된 메시지로 남는다(순서·읽음 위치가 바뀌지 않게 행은 둔다)
    seen = [m for m in _messages(client, b) if m["id"] == mid]
    assert seen and seen[0]["deleted"] is True and seen[0]["text"] == ""
    with SessionLocal() as db:
        row = db.get(Message, mid)
        assert row.text == "" and row.deleted_at is not None  # 서버에서도 본문이 사라진다


def test_normal_message_is_not_marked_deleted(client, family):
    a, _, _ = family
    _send(client, a, "안녕")
    assert _messages(client, a)[-1]["deleted"] is False


def test_only_author_can_delete(client, family):
    a, b, _ = family
    mid = _send(client, a, "내 메시지")
    r = _delete(client, b, mid)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert [m for m in _messages(client, a) if m["id"] == mid][0]["text"] == "내 메시지"


def test_delete_is_idempotent(client, family):
    a, _, _ = family
    mid = _send(client, a, "두 번 지워도")
    assert _delete(client, a, mid).status_code == 200
    again = _delete(client, a, mid)
    assert again.status_code == 200 and again.json()["deleted"] is True


def test_unknown_message_is_404(client, family):
    a, _, _ = family
    assert _delete(client, a, 999999).status_code == 404


def test_other_family_cannot_see_or_delete(client, family, other_family):
    a, _, _ = family
    mid = _send(client, a, "우리 가족 메시지")
    r = _delete(client, other_family, mid)
    assert r.status_code == 404  # 존재 여부를 숨긴다
    assert [m for m in _messages(client, a) if m["id"] == mid][0]["deleted"] is False


def test_direct_room_message_is_hidden_from_third_member(client, trio):
    a, b, c = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    mid = _send(client, a, "둘만의 대화", room_id=room)
    assert (
        _delete(client, c, mid, room_id=room).status_code == 404
    )  # 참여자가 아니면 방이 없는 것처럼
    assert (
        _delete(client, c, mid).status_code == 404
    )  # 가족 전체방 기준으로도 이 방 메시지가 아니다
    assert _delete(client, a, mid, room_id=room).status_code == 200


def test_message_of_another_room_cannot_be_deleted_through_wrong_room(client, trio):
    a, b, _ = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    mid = _send(client, a, "가족방 메시지")
    assert _delete(client, a, mid, room_id=room).status_code == 404


def test_assistant_message_cannot_be_deleted(client, family):
    a, _, _ = family
    mid = _send(client, a, "@가비 에게 보낸 글")
    with SessionLocal() as db:
        get_or_create_assistant(db)  # 가비 계정(실제 서버는 첫 @가비 호출 때 만든다)
        row = db.get(Message, mid)
        row.user_id = ASSISTANT_USER_ID  # 가비가 올린 답으로 바꿔 둔다
        db.commit()
    r = _delete(client, a, mid)
    assert r.status_code == 403 and r.json()["code"] == "forbidden"


def test_deleted_message_is_hidden_from_search_and_ai(client, family):
    a, b, _ = family
    keep = _send(client, a, "병원 예약 화요일")
    gone = _send(client, b, "병원 예약 취소")
    assert _delete(client, b, gone).status_code == 200
    r = client.get(SEARCH, params={"q": "병원"}, headers=a)
    assert [i["id"] for i in r.json()["items"]] == [keep]
    with SessionLocal() as db:
        group_id = db.get(Message, keep).group_id
        texts = [m.text for m, _name in ai_repository.recent_messages(db, group_id, 100)]
    assert "병원 예약 취소" not in texts and "병원 예약 화요일" in texts


def test_deleting_photo_message_removes_attachment_and_files(client, family, tmp_path):
    a, b, _ = family
    sent = _photo(client, a)
    aid, mid = sent["attachment"]["id"], sent["id"]
    photo_dir = Path(tmp_path) / "chat_photos"
    assert (photo_dir / f"{aid}.jpg").exists() and (photo_dir / f"{aid}_t.jpg").exists()
    assert client.get(f"{PHOTOS}/{aid}", headers=b).status_code == 200
    assert len(client.get(MEDIA, headers=b).json()["items"]) == 1

    r = _delete(client, a, mid)
    assert r.status_code == 200 and r.json()["deleted"] is True and r.json()["attachment"] is None
    assert not (photo_dir / f"{aid}.jpg").exists() and not (photo_dir / f"{aid}_t.jpg").exists()
    assert client.get(f"{PHOTOS}/{aid}", headers=b).status_code == 404
    assert client.get(MEDIA, headers=b).json()["items"] == []
    with SessionLocal() as db:
        assert db.scalar(select(MessageAttachment).where(MessageAttachment.id == aid)) is None
    shown = [m for m in _messages(client, b) if m["id"] == mid][0]
    assert shown["deleted"] is True and shown["attachment"] is None


def test_room_list_last_message_shows_deleted(client, family):
    a, b, _ = family
    mid = _send(client, a, "마지막 메시지")
    assert _delete(client, a, mid).status_code == 200
    family_room = client.get(ROOMS, headers=b).json()[0]
    assert family_room["last_message"]["id"] == mid
    assert (
        family_room["last_message"]["deleted"] is True and family_room["last_message"]["text"] == ""
    )


def test_requires_login(client):
    assert client.delete(f"{MSG}/1").status_code == 401
