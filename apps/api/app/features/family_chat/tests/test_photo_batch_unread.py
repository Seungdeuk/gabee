"""여러 장 올리기: 같은 묶음 번호(batch_id)의 사진은 안 읽은 수에서 1건으로 센다(채팅 화면은 묶음을 한 덩어리로 보여 준다)."""

import io

import httpx
import pytest
from PIL import Image

from app.features.family_chat import photo_service as ps
from app.shared.config import settings
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
ROOMS = "/family-chat/rooms"
UNREAD = "/family-chat/unread"
BATCH = "a1b2c3d4e5f6"
OTHER = "f6e5d4c3b2a1"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ps.upload_limiter._failures.clear()

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)


def _send(client, headers, batch_id=None, room_id=None):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    form = {}
    if batch_id:
        form["batch_id"] = batch_id
    if room_id:
        form["room_id"] = room_id
    r = client.post(
        PHOTOS,
        files={"file": ("a.jpg", out.getvalue(), "image/jpeg")},
        data=form or None,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r


def _unread(client, headers) -> int:
    return client.get(UNREAD, headers=headers).json()["unread"]


def test_five_photos_in_one_batch_count_as_one_unread(client, family):
    a, b, _ = family
    for _ in range(5):
        _send(client, a, BATCH)
    assert _unread(client, b) == 1
    assert _unread(client, a) == 0


def test_batches_single_photos_and_text_each_count_once(client, family):
    a, b, _ = family
    for _ in range(3):
        _send(client, a, BATCH)
    for _ in range(2):
        _send(client, a, OTHER)
    _send(client, a)  # 묶음 번호 없는 사진 한 장
    client.post(MSG, json={"text": "안녕"}, headers=a)
    assert _unread(client, b) == 4  # 묶음 2 + 낱장 1 + 글 1


def test_the_family_room_list_also_counts_a_batch_once(client, family):
    a, b, _ = family
    for _ in range(5):
        _send(client, a, BATCH)
    rooms = client.get(ROOMS, headers=b).json()
    assert [r["unread"] for r in rooms if r["kind"] == "family"] == [1]


def test_direct_room_list_counts_a_batch_once(client, family):
    a, b, _ = family
    me_b = client.get("/family-group/me", headers=b).json()["id"]
    room = client.post("/family-chat/rooms/direct", json={"user_id": me_b}, headers=a).json()["id"]
    for _ in range(4):
        _send(client, a, BATCH, room_id=room)
    _send(client, a, room_id=room)
    direct = [r for r in client.get(ROOMS, headers=b).json() if r["kind"] == "direct"]
    assert [r["unread"] for r in direct] == [2]  # 묶음 1 + 낱장 1


def test_the_same_batch_id_from_two_senders_is_counted_separately(client, family):
    """묶음 번호는 앱이 만든다: 다른 사람이 같은 번호를 써도 두 사람의 사진을 합쳐 세지 않는다."""
    a, b, group = family
    c = signup(client, "삼촌")
    assert join_family(client, a, group["invite_code"], c).status_code == 200
    for _ in range(2):
        _send(client, a, BATCH)
    for _ in range(2):
        _send(client, b, BATCH)
    assert _unread(client, c) == 2  # a 의 묶음 1 + b 의 묶음 1


def test_a_numeric_batch_id_never_merges_with_a_message_id(client, family):
    """묶음 번호가 숫자여도 같은 숫자의 다른 메시지 id 와 한 건으로 합쳐지지 않는다."""
    a, b, _ = family
    first = _send(client, a).json()["id"]  # 묶음 번호 없는 낱장
    numeric = f"{first:08d}"  # 형식(8~32자 영숫자)을 지키는 숫자 묶음 번호
    _send(client, a, numeric)
    assert _unread(client, b) == 2
