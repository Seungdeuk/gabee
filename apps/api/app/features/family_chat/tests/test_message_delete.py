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


# ── 리뷰 보강: 삭제 알림(열어 둔 화면), 파일 삭제 순서, 필터·경로 시험 ──────────


DELETED = "/family-chat/messages/deleted"


def test_deleted_since_lists_recent_deletions_for_open_screens(client, family):
    """앱은 새 메시지만 조회하므로, 이미 받아 둔 메시지가 지워졌음을 이 조회로 알 수 있어야 한다."""
    a, b, _ = family
    first = _send(client, a, "먼저")
    second = _send(client, a, "나중")
    start = client.get(DELETED, params={"since": "2000-01-01T00:00:00Z"}, headers=b)
    assert start.status_code == 200 and start.json()["message_ids"] == []
    mark = start.json()["server_time"]  # 다음 조회의 기준(서버 시계라 기기 시계와 어긋나도 괜찮다)
    assert _delete(client, a, first).status_code == 200
    r = client.get(DELETED, params={"since": mark}, headers=b)
    assert r.status_code == 200
    assert r.json()["message_ids"] == [first]
    assert second not in r.json()["message_ids"]
    later = client.get(DELETED, params={"since": r.json()["server_time"]}, headers=b)
    assert later.json()["message_ids"] == []  # 같은 삭제를 다시 알리지 않는다


def test_deleted_since_respects_room_access(client, trio, other_family):
    a, b, c = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    mid = _send(client, a, "둘만의 대화", room_id=room)
    assert _delete(client, a, mid, room_id=room).status_code == 200
    since = {"since": "2000-01-01T00:00:00Z"}
    assert client.get(DELETED, params={**since, "room_id": room}, headers=b).json()[
        "message_ids"
    ] == [mid]
    assert client.get(DELETED, params={**since, "room_id": room}, headers=c).status_code == 404
    assert (
        client.get(DELETED, params={**since, "room_id": room}, headers=other_family).status_code
        == 404
    )
    assert (
        client.get(DELETED, params=since, headers=c).json()["message_ids"] == []
    )  # 가족방에는 없다
    assert client.get(DELETED, params=since).status_code == 401


def test_file_failure_keeps_message_so_delete_can_be_retried(client, family, tmp_path, monkeypatch):
    """파일을 먼저 지운다: 지우다 실패하면 아무것도 바뀌지 않아 다시 눌러 지울 수 있고, 고아 파일이 남지 않는다."""
    a, _, _ = family
    sent = _photo(client, a)
    aid, mid = sent["attachment"]["id"], sent["id"]
    real_unlink = Path.unlink
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("busy")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky)
    failed = _delete(client, a, mid)
    assert failed.status_code >= 500
    with SessionLocal() as db:
        assert db.get(Message, mid).deleted_at is None  # DB 는 그대로
        assert db.get(MessageAttachment, aid) is not None
    retry = _delete(client, a, mid)
    assert retry.status_code == 200 and retry.json()["deleted"] is True
    photo_dir = Path(tmp_path) / "chat_photos"
    assert not (photo_dir / f"{aid}.jpg").exists() and not (photo_dir / f"{aid}_t.jpg").exists()


def test_filters_hide_rows_marked_deleted_even_if_text_remains(client, family):
    """text 를 비우는 것과 별개로 deleted_at 필터 자체가 검색·AI 를 막는지 고정한다."""
    a, _, _ = family
    mid = _send(client, a, "남아 있는 글자 병원")
    with SessionLocal() as db:
        row = db.get(Message, mid)
        row.deleted_at = row.created_at  # 본문은 그대로 두고 삭제 표시만
        group_id = row.group_id
        db.commit()
    assert client.get(SEARCH, params={"q": "병원"}, headers=a).json()["items"] == []
    with SessionLocal() as db:
        assert ai_repository.recent_messages(db, group_id, 100) == []


def test_direct_room_photo_delete_and_room_list(client, trio):
    a, b, _ = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    out = io.BytesIO()
    Image.new("RGB", (30, 20), (10, 200, 10)).save(out, format="JPEG")
    sent = client.post(
        PHOTOS,
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        data={"room_id": room},
        headers=a,
    )
    assert sent.status_code == 201, sent.text
    mid, aid = sent.json()["id"], sent.json()["attachment"]["id"]
    assert _delete(client, a, mid, room_id=room).status_code == 200
    assert client.get(f"{PHOTOS}/{aid}", headers=b).status_code == 404
    mine = [r for r in client.get(ROOMS, headers=b).json() if r["id"] == room][0]
    assert mine["last_message"]["deleted"] is True and mine["last_message"]["attachment"] is None


def test_around_and_mark_read_work_with_deleted_message(client, family):
    a, b, _ = family
    ids = [_send(client, a, f"메시지 {i}") for i in range(5)]
    assert _delete(client, a, ids[2]).status_code == 200
    around = client.get(MSG, params={"around_id": ids[2], "limit": 4}, headers=b).json()
    center = [m for m in around if m["id"] == ids[2]][0]
    assert center["deleted"] is True and center["text"] == ""
    r = client.post("/family-chat/read", json={"message_id": ids[2]}, headers=b)
    assert (
        r.status_code == 200 and r.json()["last_read_message_id"] >= ids[2]
    )  # 삭제된 메시지도 읽음 위치로 쓸 수 있다


def test_deleting_someone_elses_deleted_message_is_still_forbidden(client, family):
    a, b, _ = family
    mid = _send(client, a, "지울 메시지")
    assert _delete(client, a, mid).status_code == 200
    assert _delete(client, b, mid).status_code == 403
