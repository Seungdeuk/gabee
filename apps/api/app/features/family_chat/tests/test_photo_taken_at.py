"""사진 촬영일(`message_attachments.taken_at`, T05-a): 서버가 EXIF 의 촬영 시각 태그만 읽고(없으면 앱이 보낸 값), UTC 로 저장한다.

규칙(docs/requirements/timeline.md): 서버 EXIF 우선 → 앱 값 → 없음(NULL = 보낸 날 기준). 시간대 정보가 없으면 한국 시간으로 본다.
범위(1990-01-01 ~ 현재+1일) 밖·형식 오류는 버리고 업로드는 막지 않는다. GPS·기기 정보는 읽지도 저장하지도 응답하지도 않는다."""

import io
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image
from sqlalchemy import inspect, select

from app.features.family_chat import photo_service as ps
from app.features.family_chat.models import MessageAttachment
from app.shared.config import settings
from app.shared.db import SessionLocal, engine
from app.shared.llm import client as llm

PHOTOS = "/family-chat/photos"
MSG = "/family-chat/messages"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ps.upload_limiter._failures.clear()

    def boom(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(httpx, "post", boom)


def _image(
    when: str | None = None,
    offset: str | None = None,
    gps: bool = False,
    device: bool = False,
    fmt: str = "JPEG",
) -> bytes:
    image = Image.new("RGB", (40, 30), (200, 30, 30))
    out = io.BytesIO()
    exif = Image.Exif()
    if device:
        exif[0x010F] = "SecretCam"
        exif[0x0110] = "Model-X"
        exif[0x0131] = "Editor-9"
    sub = exif.get_ifd(0x8769)
    if when is not None:
        sub[0x9003] = when
    if offset is not None:
        sub[0x9011] = offset
    if gps:
        place = exif.get_ifd(0x8825)
        place[1], place[2] = "N", (37.0, 33.0, 59.0)
        place[3], place[4] = "E", (126.0, 58.0, 41.0)
    if fmt == "JPEG":
        image.save(out, format="JPEG", exif=exif)
    else:
        image.save(out, format=fmt)
    return out.getvalue()


def _post(client, headers, data, **form):
    return client.post(
        PHOTOS, files={"file": ("a.jpg", data, "image/jpeg")}, data=form or None, headers=headers
    )


def _row(attachment_id: str) -> MessageAttachment:
    with SessionLocal() as db:
        return db.scalars(
            select(MessageAttachment).where(MessageAttachment.id == attachment_id)
        ).one()


def _utc(value) -> datetime:
    """SQLite 는 시간대를 돌려주지 않는다: 시간대 없는 값은 UTC 로 본다."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _stored(client, headers, data, **form):
    r = _post(client, headers, data, **form)
    assert r.status_code == 201, r.text
    body = r.json()
    return body, _row(body["attachment"]["id"]).taken_at


# ---------- 순수 함수 ----------

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def test_read_taken_at_uses_offset_when_present():
    got = ps.read_taken_at(_image("2024:10:05 14:30:00", "+09:00"), NOW)
    assert got == datetime(2024, 10, 5, 5, 30, tzinfo=UTC)
    got = ps.read_taken_at(_image("2024:10:05 14:30:00", "-05:00"), NOW)
    assert got == datetime(2024, 10, 5, 19, 30, tzinfo=UTC)


def test_read_taken_at_assumes_korea_time_without_offset():
    got = ps.read_taken_at(_image("2024:10:05 14:30:00"), NOW)
    assert got == datetime(2024, 10, 5, 5, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "when",
    [
        "1989:12:31 23:59:59",
        "2026:11:14 12:00:01",
        "2999:01:01 00:00:00",
        "not a date",
        "",
        "2024:13:40 99:99:99",
        "0001:01:01 00:00:00",  # 연도 극단값: UTC 변환에서 OverflowError 가 나도 500 이 되면 안 된다
        "9999:12:31 23:59:59",
    ],
)
def test_read_taken_at_drops_out_of_range_and_garbage(when):
    assert ps.read_taken_at(_image(when), NOW) is None


def test_an_invalid_offset_keeps_the_time_as_korea_time():
    assert ps.read_taken_at(_image("2024:10:05 14:30:00", "+25:00"), NOW) == datetime(
        2024, 10, 5, 5, 30, tzinfo=UTC
    )
    assert ps.read_taken_at(_image("2024:10:05 14:30:00", "KST"), NOW) == datetime(
        2024, 10, 5, 5, 30, tzinfo=UTC
    )


def test_png_exif_is_not_read_by_the_server_and_png_is_never_decoded_a_second_time(
    monkeypatch, client, family
):
    """PNG 의 EXIF 청크는 이미지 데이터 뒤에 올 수 있어 읽으려면 전체를 다시 디코딩해야 한다(최대 2500만 화소). 비용 대신 서버는 PNG 의
    EXIF 를 읽지 않고 앱이 보낸 값만 쓴다. 카메라가 만드는 사진은 대부분 JPEG 라 잃는 것이 거의 없다."""
    from PIL import PngImagePlugin

    out = io.BytesIO()
    exif = Image.Exif()
    exif.get_ifd(0x8769)[0x9003] = "2024:10:05 14:30:00"
    Image.new("RGB", (8, 8)).save(out, format="PNG", exif=exif)
    png_with_exif = out.getvalue()
    assert ps.read_taken_at(png_with_exif, NOW) is None  # 서버는 읽지 않는다
    a, _, _ = family
    _, stored = _stored(client, a, png_with_exif, taken_at="2024-10-05T14:30:00+09:00")
    assert _utc(stored) == datetime(2024, 10, 5, 5, 30, tzinfo=UTC)  # 앱 값은 쓴다

    loads = []
    real_load = PngImagePlugin.PngImageFile.load

    def spy(
        self, *args, **kwargs
    ):  # read_taken_at 은 모든 예외를 삼키므로, 예외 대신 호출 여부를 기록해서 본다
        loads.append(1)
        return real_load(self, *args, **kwargs)

    monkeypatch.setattr(PngImagePlugin.PngImageFile, "load", spy)
    assert ps.read_taken_at(_image(fmt="PNG"), NOW) is None
    assert (
        loads == []
    )  # EXIF 가 없는 PNG 를 전체 디코딩하지 않았다(process_image 에서 이미 한 번 디코딩한다)


def test_read_taken_at_accepts_the_range_edges():
    assert ps.read_taken_at(_image("1990:01:01 09:00:00"), NOW) == datetime(
        1990, 1, 1, 0, 0, tzinfo=UTC
    )
    assert ps.read_taken_at(_image("2026:11:13 20:00:00"), NOW) is not None  # 현재+1일 이내


def test_read_taken_at_without_exif_or_with_broken_bytes_is_none():
    assert ps.read_taken_at(_image(), NOW) is None
    assert ps.read_taken_at(_image(fmt="PNG"), NOW) is None
    assert ps.read_taken_at(b"not an image", NOW) is None


def test_parse_client_taken_at():
    assert ps.parse_client_taken_at("2024-10-05T14:30:00+09:00", NOW) == datetime(
        2024, 10, 5, 5, 30, tzinfo=UTC
    )
    assert ps.parse_client_taken_at("2024-10-05T05:30:00Z", NOW) == datetime(
        2024, 10, 5, 5, 30, tzinfo=UTC
    )
    assert ps.parse_client_taken_at("2024-10-05T14:30:00", NOW) == datetime(
        2024, 10, 5, 5, 30, tzinfo=UTC
    )  # 시간대 없으면 한국 시간
    assert ps.parse_client_taken_at("2024:10:05 14:30:00", NOW) == datetime(
        2024, 10, 5, 5, 30, tzinfo=UTC
    )  # EXIF 형식도 받는다


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "abc",
        "2024-13-45T00:00:00",
        "1989-12-31T00:00:00Z",
        "2999-01-01T00:00:00Z",
        "0001:01:01 00:00:00",  # 19자라 길이 제한에 걸리지 않는다: 500 이 아니라 무시해야 한다
        "0001-01-01T00:00:00+14:00",
        "9999-12-31T23:59:59-12:00",
    ],
)
def test_parse_client_taken_at_ignores_bad_values(value):
    assert ps.parse_client_taken_at(value, NOW) is None


# ---------- 업로드 API ----------


def test_server_exif_is_stored_as_utc_and_returned(client, family):
    a, _, _ = family
    body, stored = _stored(client, a, _image("2024:10:05 14:30:00", "+09:00"))
    assert _utc(stored) == datetime(2024, 10, 5, 5, 30, tzinfo=UTC)
    assert _utc(body["attachment"]["taken_at"]) == datetime(2024, 10, 5, 5, 30, tzinfo=UTC)


def test_no_exif_leaves_taken_at_empty(client, family):
    a, _, _ = family
    for fmt in ("JPEG", "PNG", "WEBP"):
        body, stored = _stored(client, a, _image(fmt=fmt))
        assert stored is None
        assert body["attachment"]["taken_at"] is None


def test_server_exif_wins_over_the_app_value(client, family):
    a, _, _ = family
    _, stored = _stored(
        client, a, _image("2024:10:05 14:30:00", "+09:00"), taken_at="2023-01-01T00:00:00Z"
    )
    assert _utc(stored) == datetime(2024, 10, 5, 5, 30, tzinfo=UTC)


def test_app_value_is_used_when_the_server_finds_none(client, family):
    a, _, _ = family
    _, stored = _stored(client, a, _image(), taken_at="2024-10-05T14:30:00+09:00")
    assert _utc(stored) == datetime(2024, 10, 5, 5, 30, tzinfo=UTC)
    _, stored = _stored(
        client, a, _image(), taken_at="2024-10-05T14:30:00"
    )  # 시간대 없음 → 한국 시간
    assert _utc(stored) == datetime(2024, 10, 5, 5, 30, tzinfo=UTC)


def test_out_of_range_and_bad_values_do_not_block_the_upload(client, family):
    a, _, _ = family
    tomorrow_plus = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    extreme = ("0001:01:01 00:00:00", "0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-12:00")
    for value in ("1989-12-31T00:00:00Z", tomorrow_plus, "abc", "2024-13-45T00:00:00", *extreme):
        _, stored = _stored(client, a, _image(), taken_at=value)
        assert stored is None, value
    for when in ("1989:01:01 00:00:00", "0001:01:01 00:00:00", "9999:12:31 23:59:59"):
        _, stored = _stored(
            client, a, _image(when)
        )  # EXIF 도 같은 범위 검사(극단값이 500 이 되면 안 된다)
        assert stored is None, when


def test_a_value_longer_than_forty_characters_is_a_form_error(client, family):
    a, _, _ = family
    r = _post(client, a, _image(), taken_at="2024-10-05T14:30:00+09:00" + "0" * 20)
    assert r.status_code == 422
    r = _post(client, a, _image(), taken_at="x" * 40)  # 길이는 맞지만 날짜가 아니다 → 무시
    assert r.status_code == 201
    assert r.json()["attachment"]["taken_at"] is None


def test_corrupt_exif_values_do_not_break_the_upload(client, family):
    a, _, _ = family
    for when in ("garbage", "2024:99:99 99:99:99", "\u0000\u0000"):
        body, stored = _stored(client, a, _image(when, "bad"))
        assert stored is None
        assert body["attachment"]["taken_at"] is None


def test_gps_and_device_tags_are_never_stored_or_returned(client, family):
    a, _, _ = family
    data = _image("2024:10:05 14:30:00", "+09:00", gps=True, device=True)
    sent = Image.open(
        io.BytesIO(data)
    ).getexif()  # 입력에 위치·기기 정보가 실제로 들어 있는지(거짓 통과 방지)
    assert sent.get(0x010F) == "SecretCam" and sent.get_ifd(0x8825)
    r = _post(client, a, data)
    assert r.status_code == 201
    body = r.json()
    attachment = body["attachment"]
    # 응답: 촬영 시각 외 메타데이터가 없다
    text = r.text
    for secret in (
        "SecretCam",
        "Model-X",
        "Editor-9",
        "37.0",
        "126.0",
        "gps",
        "GPS",
        "exif",
        "make",
    ):
        assert secret not in text, secret
    # 저장된 사본·썸네일: EXIF 가 없다
    for size in ("full", "thumb"):
        img = client.get(f"{PHOTOS}/{attachment['id']}?size={size}", headers=a)
        assert img.status_code == 200
        stored = Image.open(io.BytesIO(img.content))
        assert not stored.getexif()
        assert not stored.getexif().get_ifd(0x8825)
        assert b"SecretCam" not in img.content and b"Model-X" not in img.content
    # DB: 촬영 시각 외에 메타데이터 칸이 늘지 않았다
    columns = {c["name"] for c in inspect(engine).get_columns("message_attachments")}  # 실제 DB 칸
    assert columns == {
        "id", "message_id", "group_id", "room_id", "kind", "path", "thumb_path", "batch_id",
        "width", "height", "size_bytes", "filename", "content_type", "created_at", "taken_at",
    }  # fmt: skip
    assert _utc(attachment["taken_at"]) == datetime(2024, 10, 5, 5, 30, tzinfo=UTC)


def test_taken_at_values_are_not_logged(client, family, caplog):
    a, _, _ = family
    with caplog.at_level(
        logging.DEBUG
    ):  # 디버그 로그를 켜도 값이 새지 않아야 한다(Pillow 는 EXIF 태그 값을 DEBUG 로 찍는다)
        full = _image("2024:10:05 14:30:00", "+09:00", gps=True, device=True)
        _post(client, a, full, taken_at="2023-02-03T00:00:00Z")
        _post(client, a, _image("garbage"), taken_at="2023-02-03T00:00:00Z")
    joined = " ".join(r.getMessage() for r in caplog.records)
    for text in (
        "2024:10:05",
        "2024-10-05",
        "2023-02-03",
        "garbage",
        "SecretCam",
        "Model-X",
        "Editor-9",
    ):
        assert text not in joined, text


def test_message_list_returns_taken_at_and_old_photos_have_none(client, family):
    a, b, _ = family
    with_exif, _ = _stored(client, a, _image("2024:10:05 14:30:00", "+09:00"))
    plain, _ = _stored(client, a, _image())
    r = client.get(MSG, params={"latest": "true"}, headers=b)
    assert r.status_code == 200, r.text
    listed = r.json()
    by_id = {m["attachment"]["id"]: m["attachment"] for m in listed if m.get("attachment")}
    assert _utc(by_id[with_exif["attachment"]["id"]]["taken_at"]) == datetime(
        2024, 10, 5, 5, 30, tzinfo=UTC
    )
    assert by_id[plain["attachment"]["id"]]["taken_at"] is None


def test_other_families_cannot_read_the_photo_or_its_date(client, family, other_family):
    a, _, _ = family
    body, _ = _stored(client, a, _image("2024:10:05 14:30:00", "+09:00"))
    r = client.get(f"{PHOTOS}/{body['attachment']['id']}", headers=other_family)
    assert r.status_code == 404
    listed = client.get(MSG, params={"latest": "true"}, headers=other_family)
    assert "taken_at" not in listed.text  # 다른 가족의 목록에는 이 사진도 촬영일도 나오지 않는다
