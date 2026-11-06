"""여러 장 올리기: 같은 묶음 번호(batch_id)로 올린 사진이 메시지·사진 모음에서 한 묶음으로 내려온다."""

import io

import httpx
import pytest
from PIL import Image

from app.features.family_chat import media_service as ms
from app.features.family_chat import photo_service as ps
from app.shared.config import settings
from app.shared.llm import client as llm

PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"
MEDIA = "/family-chat/media"
BATCH = "a1b2c3d4e5f6"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ps.upload_limiter._failures.clear()
    ms.limiter._failures.clear()

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    return out.getvalue()


def _send(client, headers, batch_id=None):
    form = {"batch_id": batch_id} if batch_id is not None else None
    return client.post(
        PHOTOS, files={"file": ("a.jpg", _jpeg(), "image/jpeg")}, data=form, headers=headers
    )


def test_batch_id_is_saved_and_returned_with_the_message(client, family):
    a, b, _ = family
    first = _send(client, a, BATCH)
    second = _send(client, a, BATCH)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["attachment"]["batch_id"] == BATCH
    got = client.get(MSG, params={"latest": True}, headers=b).json()  # 다른 구성원이 불러와도 같다
    assert [m["attachment"]["batch_id"] for m in got] == [BATCH, BATCH]


def test_photo_without_batch_id_has_none(client, family):
    a, _, _ = family
    r = _send(client, a)
    assert r.status_code == 201
    assert r.json()["attachment"]["batch_id"] is None


@pytest.mark.parametrize("bad", ["short", "x" * 33, "has space 123456", "한글한글한글한글한글한글"])
def test_invalid_batch_id_is_rejected(client, family, bad):
    a, _, _ = family
    assert _send(client, a, bad).status_code == 422


def test_media_list_carries_batch_id(client, family):
    a, b, _ = family
    _send(client, a, BATCH)
    _send(client, a)
    items = client.get(MEDIA, params={"kind": "image"}, headers=b).json()["items"]
    assert sorted((i["batch_id"] or "") for i in items) == ["", BATCH]
