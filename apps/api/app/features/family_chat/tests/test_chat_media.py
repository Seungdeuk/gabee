"""채팅방 사진·파일·동영상 모음: 최신순·커서, 종류 필터, 개수, 방 분리, 권한 격리, 제한."""

import io

import httpx
import pytest
from PIL import Image

from app.features.family_chat import media_service as ms
from app.features.family_chat import photo_service as ps
from app.shared.config import settings
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

MEDIA = "/family-chat/media"
PHOTOS = "/family-chat/photos"
DIRECT_ROOM = "/family-chat/rooms/direct"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ps.upload_limiter._failures.clear()
    ms.limiter._failures.clear()

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


def _send(client, headers, room_id=None, color=(200, 30, 30)):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(out, format="JPEG")
    form = {"room_id": room_id} if room_id else None
    r = client.post(
        PHOTOS, files={"file": ("a.jpg", out.getvalue(), "image/jpeg")}, data=form, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_lists_newest_first_with_fields_and_counts(client, family):
    a, b, _ = family
    first = _send(client, a)
    second = _send(client, b)
    client.post(
        "/family-chat/messages", json={"text": "글자만"}, headers=a
    )  # 글 메시지는 모음에 없다
    r = client.get(MEDIA, headers=a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["message_id"] for i in body["items"]] == [second["id"], first["id"]]
    item = body["items"][0]
    assert item["attachment_id"] == second["attachment"]["id"]
    assert item["kind"] == "image" and item["user_name"] == "수진"
    assert item["user_id"] == _uid(client, b)
    assert item["url"] == second["attachment"]["url"]
    assert item["thumb_url"] == second["attachment"]["thumb_url"]
    assert item["width"] == 40 and item["height"] == 30 and item["size_bytes"] > 0
    assert body["next_before_id"] is None
    assert body["counts"] == {"image": 2, "file": 0, "video": 0}


def test_cursor_paging(client, family):
    a, _, _ = family
    ids = [_send(client, a)["id"] for _ in range(5)]
    p1 = client.get(MEDIA, params={"limit": 2}, headers=a).json()
    assert [i["message_id"] for i in p1["items"]] == [ids[4], ids[3]]
    assert p1["next_before_id"] == ids[3]
    p2 = client.get(MEDIA, params={"limit": 2, "before_id": p1["next_before_id"]}, headers=a).json()
    assert [i["message_id"] for i in p2["items"]] == [ids[2], ids[1]]
    p3 = client.get(MEDIA, params={"limit": 2, "before_id": p2["next_before_id"]}, headers=a).json()
    assert [i["message_id"] for i in p3["items"]] == [ids[0]]
    assert p3["next_before_id"] is None
    assert p3["counts"]["image"] == 5  # 개수는 쪽과 상관없이 전체


def test_kind_filter_and_validation(client, family):
    a, _, _ = family
    _send(client, a)
    for kind in ("image", "all"):
        assert len(client.get(MEDIA, params={"kind": kind}, headers=a).json()["items"]) == 1
    for kind in ("file", "video"):
        body = client.get(MEDIA, params={"kind": kind}, headers=a).json()
        assert body["items"] == [] and body["next_before_id"] is None
        assert body["counts"]["image"] == 1
    assert client.get(MEDIA, params={"kind": "audio"}, headers=a).status_code == 422
    assert client.get(MEDIA, params={"limit": 0}, headers=a).status_code == 422
    assert client.get(MEDIA, params={"limit": 101}, headers=a).status_code == 422


def test_family_room_and_direct_room_are_separate(client, trio):
    a, b, c = trio
    family_msg = _send(client, a)
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    direct_msg = _send(client, a, room_id=room)

    fam = client.get(MEDIA, headers=c).json()  # 가족 전체방은 room_id 없이
    assert [i["message_id"] for i in fam["items"]] == [family_msg["id"]]
    assert fam["counts"]["image"] == 1
    d = client.get(MEDIA, params={"room_id": room}, headers=b).json()
    assert [i["message_id"] for i in d["items"]] == [direct_msg["id"]]
    assert d["counts"]["image"] == 1
    # 가족 전체방 id 를 직접 지정해도 같은 모음
    family_room_id = next(
        r["id"] for r in client.get("/family-chat/rooms", headers=a).json() if r["kind"] == "family"
    )
    same = client.get(MEDIA, params={"room_id": family_room_id}, headers=a).json()
    assert [i["message_id"] for i in same["items"]] == [family_msg["id"]]


def test_isolation_other_family_and_foreign_direct_room(client, trio, other_family):
    a, b, c = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    direct = _send(client, a, room_id=room)
    # 같은 가족의 제3자: 그 방은 404, 가족 전체방 모음·개수에는 1:1 사진이 없다
    assert client.get(MEDIA, params={"room_id": room}, headers=c).status_code == 404
    fam = client.get(MEDIA, headers=c).json()
    assert fam["items"] == [] and fam["counts"] == {"image": 0, "file": 0, "video": 0}
    # 다른 가족: 그 방은 404, 자기 가족 모음은 비어 있다
    assert client.get(MEDIA, params={"room_id": room}, headers=other_family).status_code == 404
    other = client.get(MEDIA, headers=other_family).json()
    assert other["items"] == [] and other["counts"]["image"] == 0
    # 없는 방도 같은 404
    assert client.get(MEDIA, params={"room_id": "nope"}, headers=a).status_code == 404
    assert direct["attachment"]["id"]


def test_returned_urls_serve_the_photo_with_same_permissions(client, trio, other_family):
    a, b, c = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    _send(client, a, room_id=room)
    item = client.get(MEDIA, params={"room_id": room}, headers=b).json()["items"][0]
    for url in (item["url"], item["thumb_url"]):
        got = client.get(url, headers=b)
        assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
        assert client.get(url, headers=c).status_code == 404
        assert client.get(url, headers=other_family).status_code == 404


def test_requires_login(client):
    assert client.get(MEDIA).status_code == 401


def test_rate_limit_returns_429(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(ms, "LIMIT_PER_MINUTE", 3)
    for _ in range(3):
        assert client.get(MEDIA, headers=a).status_code == 200
    r = client.get(MEDIA, headers=a)
    assert r.status_code == 429 and "retry-after" in r.headers
