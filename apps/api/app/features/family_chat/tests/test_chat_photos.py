"""채팅 사진: 보내기·보기, 방별 접근 제한, EXIF 제거, 크기·형식 방어, 사진 메시지는 AI 로 가지 않는다."""

import io

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.features.family_chat import ai_repository
from app.features.family_chat import photo_service as ps
from app.features.family_chat import repository as chat_repo
from app.features.family_chat.models import Message, MessageAttachment
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
ROOMS = "/family-chat/rooms"
DIRECT_ROOM = "/family-chat/rooms/direct"
UNREAD = "/family-chat/unread"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """사진은 임시 폴더에 저장하고, 업로드 한도는 시험마다 새로 센다. 사진 보내기는 AI 를 부르지 않는다."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ps.upload_limiter._failures.clear()

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)


@pytest.fixture
def trio(client, family):
    a, b, group = family
    c = signup(client, "삼촌")
    r = join_family(client, a, group["invite_code"], c)
    assert r.status_code == 200
    return a, b, c


def _uid(client, headers):
    return client.get("/family-group/me", headers=headers).json()["id"]


def _jpeg(size=(40, 30), color=(200, 30, 30), exif=False) -> bytes:
    image = Image.new("RGB", size, color)
    out = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x0112] = 6  # 오른쪽으로 90도 회전
        data[0x010F] = "SecretCam"  # 제조사
        image.save(out, format="JPEG", exif=data)
    else:
        image.save(out, format="JPEG")
    return out.getvalue()


def _png(size=(20, 20)) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", size, (0, 128, 255, 100)).save(out, format="PNG")
    return out.getvalue()


def _send(client, headers, data=None, room_id=None, name="a.jpg", ctype="image/jpeg"):
    files = {"file": (name, data if data is not None else _jpeg(), ctype)}
    form = {"room_id": room_id} if room_id else None
    return client.post(PHOTOS, files=files, data=form, headers=headers)


def test_send_photo_creates_message_with_attachment(client, family):
    a, b, _ = family
    r = _send(client, a, _jpeg((3000, 2000)))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["text"] == "" and body["user_name"] == "지민"
    att = body["attachment"]
    assert att["kind"] == "image" and att["url"].startswith("/family-chat/photos/")
    assert att["thumb_url"] == att["url"] + "?size=thumb"
    assert max(att["width"], att["height"]) == 1600  # 긴 변 1600px 로 줄었다
    # 다른 구성원이 목록에서 사진 메시지를 본다
    got = client.get(MSG, params={"latest": True}, headers=b).json()
    assert [m["attachment"]["id"] for m in got] == [att["id"]]
    # 원본과 썸네일 모두 JPEG, 썸네일은 400px 이하
    full = client.get(att["url"], headers=b)
    thumb = client.get(att["thumb_url"], headers=b)
    assert full.status_code == 200 and full.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(full.content)).size == (1600, 1067)
    assert max(Image.open(io.BytesIO(thumb.content)).size) <= 400
    assert (
        "immutable" in full.headers["cache-control"]
        and full.headers["x-content-type-options"] == "nosniff"
    )


def test_exif_gps_and_make_are_stripped_and_rotation_applied(client, family):
    a, _, _ = family
    r = _send(client, a, _jpeg((60, 20), exif=True))
    assert r.status_code == 201, r.text
    att = r.json()["attachment"]
    assert (att["width"], att["height"]) == (20, 60)  # 회전 반영
    image = Image.open(io.BytesIO(client.get(att["url"], headers=a).content))
    assert not image.getexif()  # 메타데이터 없음


def test_png_with_transparency_and_webp_are_accepted(client, family):
    a, _, _ = family
    assert _send(client, a, _png(), name="a.png", ctype="image/png").status_code == 201
    out = io.BytesIO()
    Image.new("RGB", (10, 10), (1, 2, 3)).save(out, format="WEBP")
    assert _send(client, a, out.getvalue(), name="a.webp", ctype="image/webp").status_code == 201


def test_rejects_non_images_unsupported_formats_and_oversize(client, family, monkeypatch):
    a, _, _ = family
    r = _send(client, a, b"not an image", name="a.jpg")
    assert r.status_code == 400 and r.json()["code"] == "invalid_image"
    gif = io.BytesIO()
    Image.new("RGB", (5, 5)).save(gif, format="GIF")
    assert _send(client, a, gif.getvalue(), name="a.gif", ctype="image/gif").status_code == 400
    monkeypatch.setattr(ps, "MAX_BYTES", 100)
    r = _send(client, a, _jpeg((200, 200)))
    assert r.status_code == 413 and r.json()["code"] == "photo_too_large"
    monkeypatch.setattr(ps, "MAX_BYTES", 8 * 1024 * 1024)
    monkeypatch.setattr(ps, "MAX_PIXELS", 100)
    r = _send(client, a, _jpeg((50, 50)))
    assert r.status_code == 400 and r.json()["code"] == "invalid_image"
    # 거절된 요청은 메시지도 파일도 남기지 않는다
    assert client.get(MSG, params={"latest": True}, headers=a).json() == []
    with SessionLocal() as db:
        assert db.scalars(select(MessageAttachment)).all() == []


def test_requires_login_and_group(client, family):
    assert client.post(PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}).status_code == 401
    lonely = signup(client, "혼자")
    r = _send(client, lonely)
    assert r.status_code == 400 and r.json()["code"] == "no_group"
    assert client.get(PHOTOS + "/abc").status_code == 401


def test_direct_room_photo_visible_only_to_the_two(client, trio, other_family):
    a, b, c = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    r = _send(client, a, room_id=room)
    assert r.status_code == 201, r.text
    att = r.json()["attachment"]
    for who in (a, b):
        assert client.get(att["url"], headers=who).status_code == 200
        assert client.get(att["thumb_url"], headers=who).status_code == 200
    # 같은 가족의 제3자, 다른 가족, 없는 사진은 모두 같은 404
    for who in (c, other_family):
        assert client.get(att["url"], headers=who).status_code == 404
        assert client.get(att["thumb_url"], headers=who).status_code == 404
    assert client.get(PHOTOS + "/nonexistent", headers=a).status_code == 404
    # 제3자는 그 방에 사진을 보낼 수도 없고, 가족 전체방 목록에도 1:1 사진이 없다
    assert _send(client, c, room_id=room).status_code == 404
    assert client.get(MSG, params={"latest": True}, headers=c).json() == []


def test_family_photo_not_visible_to_other_family(client, family, other_family):
    a, _, _ = family
    att = _send(client, a).json()["attachment"]
    assert client.get(att["url"], headers=other_family).status_code == 404


def test_etag_gives_304(client, family):
    a, b, _ = family
    att = _send(client, a).json()["attachment"]
    first = client.get(att["url"], headers=b)
    again = client.get(att["url"], headers={**b, "If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert client.get(att["url"] + "?size=bogus", headers=b).status_code == 422


def test_photo_counts_as_unread_and_sender_has_read_it(client, family):
    a, b, _ = family
    _send(client, a)
    assert client.get(UNREAD, headers=b).json()["unread"] == 1
    assert client.get(UNREAD, headers=a).json()["unread"] == 0


def test_room_list_last_message_shows_photo(client, trio):
    a, b, _ = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    _send(client, a, room_id=room)
    _send(client, a)
    rooms = client.get(ROOMS, headers=b).json()
    assert [r["kind"] for r in rooms] == ["family", "direct"]
    for r in rooms:
        assert (
            r["last_message"]["text"] == "" and r["last_message"]["attachment"]["kind"] == "image"
        )
        assert r["unread"] == 1


def test_photo_messages_are_not_sent_to_ai(client, family):
    a, _, _ = family
    _send(client, a)
    client.post(MSG, json={"text": "글자 메시지"}, headers=a)
    gid = client.get("/family-group/groups/me", headers=a).json()["id"]
    with SessionLocal() as db:
        rows = ai_repository.recent_messages(db, gid, 100)
    assert [m.text for m, _ in rows] == ["글자 메시지"]


def test_files_are_removed_when_db_save_fails(client, family, monkeypatch, tmp_path):
    a, _, _ = family

    def boom(db, message, attachment, with_check=False):
        raise RuntimeError("db down")

    monkeypatch.setattr(chat_repo, "add_photo_message", boom)
    with pytest.raises(RuntimeError):
        _send(client, a)
    assert list((tmp_path / "chat_photos").glob("*")) == []


def test_busy_and_rate_limit(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(ps, "UPLOAD_LIMIT", 2)
    assert _send(client, a).status_code == 201
    assert _send(client, a).status_code == 201
    r = _send(client, a)
    assert r.status_code == 429 and "retry-after" in r.headers
    ps.upload_limiter._failures.clear()
    for _ in range(ps.MAX_CONCURRENT):
        assert ps._slots.acquire(blocking=False)
    try:
        r = _send(client, a)
        assert r.status_code == 503 and r.json()["code"] == "photo_busy"
    finally:
        for _ in range(ps.MAX_CONCURRENT):
            ps._slots.release()


def test_body_limit_rejects_before_parsing(client, family):
    a, _, _ = family
    big = b"0" * (8 * 1024 * 1024 + 200 * 1024)
    r = client.post(PHOTOS, files={"file": ("a.jpg", big, "image/jpeg")}, headers=a)
    assert r.status_code == 413 and r.json()["code"] == "photo_too_large"


def test_stored_paths_must_have_the_server_made_shape(client, family):
    a, _, _ = family
    att = _send(client, a).json()["attachment"]
    with SessionLocal() as db:
        row = db.get(MessageAttachment, att["id"])
        row.path = "../../etc/passwd"
        db.commit()
    assert client.get(att["url"], headers=a).status_code == 404  # 이상한 경로는 읽지 않는다
    with SessionLocal() as db:
        assert db.scalars(select(Message)).first().text == ""


def _contains_secret(data: bytes) -> bool:
    return b"top-secret-note" in data


def test_jpeg_comment_and_png_text_metadata_are_stripped(client, family):
    a, b, _ = family
    # JPEG 주석(COM)
    jpeg = io.BytesIO()
    Image.new("RGB", (30, 30), (5, 5, 5)).save(jpeg, format="JPEG", comment=b"top-secret-note")
    assert _contains_secret(jpeg.getvalue())  # 시험 입력에 실제로 들어 있다
    # PNG 텍스트 청크(RGB·L)
    from PIL.PngImagePlugin import PngInfo

    pngs = []
    for mode in ("RGB", "L"):
        info = PngInfo()
        info.add_text("comment", "top-secret-note")
        png = io.BytesIO()
        Image.new(mode, (20, 20)).save(png, format="PNG", pnginfo=info)
        assert _contains_secret(png.getvalue())
        pngs.append(png.getvalue())
    for data, name, ctype in [(jpeg.getvalue(), "a.jpg", "image/jpeg")] + [
        (p, "a.png", "image/png") for p in pngs
    ]:
        att = _send(client, a, data, name=name, ctype=ctype).json()["attachment"]
        for url in (att["url"], att["thumb_url"]):
            content = client.get(url, headers=b).content
            assert not _contains_secret(content)
            assert not Image.open(io.BytesIO(content)).info.get("comment")


def test_read_position_failure_does_not_fail_the_upload(client, family, monkeypatch):
    a, _, _ = family

    def boom(*args, **kwargs):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(chat_repo, "advance_read", boom)
    r = _send(client, a)
    assert r.status_code == 201  # 사진은 이미 저장됐으니 재시도로 두 번 가지 않게 한다
    assert len(client.get(MSG, params={"latest": True}, headers=a).json()) == 1
