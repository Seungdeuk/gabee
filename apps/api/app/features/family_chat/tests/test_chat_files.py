"""채팅 문서 파일: 보내기·받기, 형식·크기 방어, 파일명 정리, 방별 접근 제한, 삭제, 사진 모음 분리, AI·검색 제외."""

import io
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from PIL import Image

from app.features.family_chat import file_service as fs
from app.features.family_chat import media_service as ms
from app.features.family_chat import photo_service as ps
from app.shared.config import settings
from app.shared.llm import client as llm
from tests.helpers import join_family, signup

FILES = "/family-chat/files"
PHOTOS = "/family-chat/photos"
MEDIA = "/family-chat/media"
MSG = "/family-chat/messages"
SEARCH = "/family-chat/search"
DIRECT_ROOM = "/family-chat/rooms/direct"
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    fs.upload_limiter._failures.clear()
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


def _zip(names: list[str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name in names:
            archive.writestr(name, "x")
    return out.getvalue()


DOCX = _zip(["[Content_Types].xml", "word/document.xml"])
XLSX = _zip(["[Content_Types].xml", "xl/workbook.xml"])
PPTX = _zip(["[Content_Types].xml", "ppt/presentation.xml"])


def _hwpx(mimetype: str = "application/hwp+zip") -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("mimetype", mimetype)
        archive.writestr("Contents/header.xml", "x")
    return out.getvalue()


HWPX = _hwpx()
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF"

VALID = {
    "a.pdf": PDF,
    "a.doc": OLE,
    "a.docx": DOCX,
    "a.xls": OLE,
    "a.xlsx": XLSX,
    "a.ppt": OLE,
    "a.pptx": PPTX,
    "a.hwp": OLE,
    "a.hwpx": HWPX,
    "a.txt": "안녕하세요 메모".encode(),
    "a.csv": b"a,b\n1,2\n",
}


def _send(client, headers, name="a.pdf", data=None, room_id=None, ctype="application/pdf"):
    if data is None:
        data = VALID.get("a" + name[name.rfind(".") :], PDF)
    form = {"room_id": room_id} if room_id else None
    return client.post(FILES, files={"file": (name, data, ctype)}, data=form, headers=headers)


def _photo(client, headers):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    r = client.post(
        PHOTOS, files={"file": ("a.jpg", out.getvalue(), "image/jpeg")}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize("name", list(VALID))
def test_allowed_documents_upload(client, family, name):
    a, _, _ = family
    r = _send(client, a, name)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["text"] == ""
    att = body["attachment"]
    assert att["kind"] == "file"
    assert att["filename"] == name
    assert att["size_bytes"] == len(VALID[name])
    assert att["content_type"] in {k.content_type for k in fs.ALLOWED.values()}
    assert att["thumb_url"] is None and att["width"] is None and att["height"] is None
    assert att["url"] == f"{FILES}/{att['id']}"


def test_korean_filename_and_download_headers(client, family):
    a, b, _ = family
    name = "가족 여행 계획서.pdf"
    att = _send(client, a, name).json()["attachment"]
    assert att["filename"] == name
    r = client.get(att["url"], headers=b)
    assert r.status_code == 200
    assert r.content == PDF
    assert r.headers["content-disposition"] == (
        f"attachment; filename*=UTF-8''{quote(name, safe='')}"
    )
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-type"] == "application/pdf"


def test_message_list_shows_file_attachment(client, family):
    a, b, _ = family
    sent = _send(client, a, "report.xlsx").json()
    listed = client.get(MSG, params={"latest": True}, headers=b).json()
    assert listed[-1]["id"] == sent["id"]
    assert listed[-1]["attachment"]["kind"] == "file"
    assert listed[-1]["attachment"]["filename"] == "report.xlsx"


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("run.exe", b"MZ\x90\x00" + b"\x00" * 64),
        ("a.zip", _zip(["a.txt"])),
        ("a.html", b"<html><script>alert(1)</script></html>"),
        ("a.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
        ("a.js", b"alert(1)"),
        ("a.sh", b"#!/bin/sh\nrm -rf /\n"),
        ("a.bat", b"@echo off"),
        ("a.png", b"\x89PNG\r\n\x1a\n"),
        ("noext", b"hello"),
        ("a.pdf.exe", PDF),
        ("a.pdf", b"MZ not a pdf"),  # 확장자-시그니처 불일치
        ("a.docx", _zip(["a.txt"])),  # 그냥 zip 을 docx 로
        ("a.docx", PDF),
        ("a.xlsx", DOCX),
        ("a.doc", PDF),
        ("a.hwpx", _zip(["a.txt"])),
        ("a.hwpx", _hwpx("text/plain")),  # mimetype 이 hwpx 가 아니다
        ("a.docx", _zip(["[Content_Types].xml"])),  # 필수 항목(word/document.xml) 없음
        ("a.xlsx", _zip(["[Content_Types].xml", "word/document.xml"])),
        ("a.pptx", _zip(["[Content_Types].xml", "xl/workbook.xml"])),
        ("a.txt", b"\xff\xfe\xfa\x81"),  # UTF-8 도 CP949 도 아니다
        ("a.csv", "a,b\n".encode("utf-16")),  # UTF-16(NUL 바이트)
        ("a.txt", b"hello\x00world"),
        ("a.txt", b"<!DOCTYPE html><html></html>"),
        ("a.txt", b"MZ\x90 program"),
        ("a.pdf", b""),
        ("a.txt", b""),
    ],
)
def test_rejected_files(client, family, name, data):
    a, _, _ = family
    r = _send(client, a, name, data)
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "invalid_file"
    assert client.get(MSG, params={"latest": True}, headers=a).json() == []


def test_oversize_file_is_413(client, family):
    a, _, _ = family
    big = b"%PDF-" + b"0" * fs.MAX_BYTES  # 한도 + 5바이트
    r = _send(client, a, "big.pdf", big)
    assert r.status_code == 413 and r.json()["code"] == "file_too_large"
    exact = b"%PDF-" + b"0" * (fs.MAX_BYTES - 5)
    assert _send(client, a, "ok.pdf", exact).status_code == 201


def test_body_limit_rejects_before_parsing(client, family):
    a, _, _ = family
    big = b"0" * (20 * 1024 * 1024 + 200 * 1024)
    r = client.post(FILES, files={"file": ("a.pdf", big, "application/pdf")}, headers=a)
    assert r.status_code == 413 and r.json()["code"] == "file_too_large"


def test_path_tricks_in_filename_are_cleaned(client, family, tmp_path):
    a, _, _ = family
    att = _send(client, a, "../../etc/passwd/보고서.pdf").json()["attachment"]
    assert att["filename"] == "보고서.pdf"
    stored = list((Path(tmp_path) / "chat_files").iterdir())
    assert [p.name for p in stored] == [f"{att['id']}.pdf"]  # 서버가 만든 이름만
    # \uc81c\uc5b4\u00b7\ubc29\ud5a5 \uc804\ud658 \ubb38\uc790\uc640 \uae08\uc9c0 \ubb38\uc790\ub294 \uc9c0\uc6b4\ub2e4(multipart \uc804\uc1a1\uc774 \uc81c\uc5b4 \ubb38\uc790\ub97c \ubc14\uafb8\ubbc0\ub85c \uc815\ub9ac \ud568\uc218\ub97c \uc9c1\uc811 \ubcf8\ub2e4)
    assert fs.clean_filename('a\r\nb\u202e<x>:"|?*.PDF') == ("abx.pdf", ".pdf")
    assert fs.clean_filename("..\\..\\win.txt\x00") == ("win.txt", ".txt")
    long_name = "가" * 300 + ".docx"
    out = _send(client, a, long_name, DOCX).json()["attachment"]["filename"]
    assert len(out) <= fs.MAX_FILENAME_CHARS and out.endswith(".docx")
    win = _send(client, a, "C:\\Users\\me\\메모.txt").json()["attachment"]["filename"]
    assert win == "메모.txt"


def test_requires_login_and_group(client, family):
    assert client.post(FILES, files={"file": ("a.pdf", PDF, "application/pdf")}).status_code == 401
    assert client.get(FILES + "/abc").status_code == 401
    lonely = signup(client, "혼자")
    r = _send(client, lonely)
    assert r.status_code == 400 and r.json()["code"] == "no_group"


def test_other_family_cannot_download(client, family, other_family):
    a, _, _ = family
    att = _send(client, a).json()["attachment"]
    assert client.get(att["url"], headers=other_family).status_code == 404
    assert client.get(FILES + "/nonexistent", headers=a).status_code == 404


def test_direct_room_file_visible_only_to_the_two(client, trio, other_family):
    a, b, c = trio
    room = client.post(DIRECT_ROOM, json={"user_id": _uid(client, b)}, headers=a).json()["id"]
    r = _send(client, a, room_id=room)
    assert r.status_code == 201, r.text
    att = r.json()["attachment"]
    for who in (a, b):
        assert client.get(att["url"], headers=who).status_code == 200
    for who in (c, other_family):
        assert client.get(att["url"], headers=who).status_code == 404
    assert _send(client, c, room_id=room).status_code == 404
    assert client.get(MSG, params={"latest": True}, headers=c).json() == []


def test_photo_url_does_not_serve_a_file_and_vice_versa(client, family):
    a, _, _ = family
    file_att = _send(client, a).json()["attachment"]
    photo_att = _photo(client, a)["attachment"]
    assert client.get(f"{PHOTOS}/{file_att['id']}", headers=a).status_code == 404
    assert client.get(f"{FILES}/{photo_att['id']}", headers=a).status_code == 404


def test_delete_removes_disk_file(client, family, tmp_path):
    a, _, _ = family
    sent = _send(client, a).json()
    directory = Path(tmp_path) / "chat_files"
    assert len(list(directory.iterdir())) == 1
    r = client.delete(f"{MSG}/{sent['id']}", headers=a)
    assert r.status_code == 200 and r.json()["attachment"] is None
    assert list(directory.iterdir()) == []
    assert client.get(sent["attachment"]["url"], headers=a).status_code == 404


def test_delete_photo_still_removes_photo_files(client, family, tmp_path):
    a, _, _ = family
    sent = _photo(client, a)
    assert len(list((Path(tmp_path) / "chat_photos").iterdir())) == 2
    assert client.delete(f"{MSG}/{sent['id']}", headers=a).status_code == 200
    assert list((Path(tmp_path) / "chat_photos").iterdir()) == []


def test_stored_path_must_have_the_server_made_shape(client, family):
    from app.features.family_chat.models import MessageAttachment
    from app.shared.db import SessionLocal

    a, _, _ = family
    att = _send(client, a).json()["attachment"]
    with SessionLocal() as db:
        row = db.get(MessageAttachment, att["id"])
        row.path = "../../etc/passwd"
        db.commit()
    assert client.get(att["url"], headers=a).status_code == 404


def test_media_collection_separates_photos_and_files(client, family):
    a, b, _ = family
    photo = _photo(client, a)
    doc = _send(client, b, "plan.pdf").json()
    _send(client, a, "x.txt")
    images = client.get(MEDIA, params={"kind": "image"}, headers=a).json()
    assert [i["message_id"] for i in images["items"]] == [photo["id"]]
    assert images["counts"] == {"image": 1, "file": 2, "video": 0}
    files = client.get(MEDIA, params={"kind": "file"}, headers=a).json()
    assert len(files["items"]) == 2
    first = files["items"][-1]
    assert first["message_id"] == doc["id"] and first["kind"] == "file"
    assert first["url"] == f"{FILES}/{first['attachment_id']}"
    assert first["thumb_url"] is None and first["width"] is None
    assert first["size_bytes"] == len(PDF)
    everything = client.get(MEDIA, headers=a).json()
    assert len(everything["items"]) == 3
    assert client.get(MEDIA, params={"kind": "video"}, headers=a).json()["items"] == []


def test_existing_photo_response_is_unchanged(client, family):
    a, _, _ = family
    att = _photo(client, a)["attachment"]
    assert att["kind"] == "image"
    assert att["url"] == f"{PHOTOS}/{att['id']}"
    assert att["thumb_url"] == f"{PHOTOS}/{att['id']}?size=thumb"
    assert att["width"] == 40 and att["height"] == 30
    assert att["filename"] is None and att["content_type"] is None


def test_cp949_and_utf8_text_are_accepted(client, family):
    a, _, _ = family
    assert _send(client, a, "a.txt", "한글 메모".encode("cp949")).status_code == 201
    assert _send(client, a, "a.csv", "\ufeff이름,값\n".encode("utf-8")).status_code == 201


def test_filename_is_nfc_and_line_separators_removed(client, family):
    a, _, _ = family
    decomposed = unicodedata.normalize("NFD", "한글 문서")
    assert decomposed != "한글 문서"
    assert fs.clean_filename(decomposed + ".pdf") == ("한글 문서.pdf", ".pdf")
    assert fs.clean_filename("a\u2028b\u2029c.txt") == ("abc.txt", ".txt")
    att = _send(client, a, decomposed + ".pdf").json()["attachment"]
    assert att["filename"] == "한글 문서.pdf"


def test_reply_preview_has_attachment_kind(client, family):
    a, b, _ = family
    photo = _photo(client, a)
    doc = _send(client, a, "plan.pdf").json()
    plain = client.post(MSG, json={"text": "그냥 글"}, headers=a).json()
    for parent, kind in ((photo, "image"), (doc, "file"), (plain, None)):
        r = client.post(MSG, json={"text": "답", "reply_to_id": parent["id"]}, headers=b)
        assert r.status_code == 201, r.text
        reply = r.json()["reply_to"]
        assert reply["attachment_kind"] == kind and reply["has_attachment"] == (kind is not None)
    listed = client.get(MSG, params={"latest": True}, headers=a).json()
    kinds = [m["reply_to"]["attachment_kind"] for m in listed if m["reply_to"]]
    assert kinds == ["image", "file", None]


def test_room_list_last_message_shows_file(client, family):
    a, b, _ = family
    _send(client, a)
    rooms = client.get("/family-chat/rooms", headers=b).json()
    last = rooms[0]["last_message"]
    assert last["text"] == "" and last["attachment"]["kind"] == "file"
    assert rooms[0]["unread"] == 1


def test_file_messages_are_not_searchable_and_not_in_ai_messages(client, family):
    a, _, group = family
    client.post(MSG, json={"text": "보통 글"}, headers=a)
    _send(client, a, "비밀계획서.pdf")
    from app.features.family_chat import ai_repository
    from app.shared.db import SessionLocal

    with SessionLocal() as db:
        texts = [m.text for m, _ in ai_repository.recent_messages(db, group["id"], 50)]
    assert texts == ["보통 글"]  # 문서 메시지(text 빈 문자열)는 AI 로 가는 메시지에 없다
    r = client.get(SEARCH, params={"q": "비밀계획서"}, headers=a)
    assert r.status_code == 200 and r.json()["items"] == []
    r = client.get(SEARCH, params={"q": "pdf"}, headers=a)
    assert r.json()["items"] == []


def test_busy_and_rate_limit(client, family, monkeypatch):
    a, _, _ = family
    monkeypatch.setattr(fs, "UPLOAD_LIMIT", 2)
    assert _send(client, a).status_code == 201
    assert _send(client, a).status_code == 201
    r = _send(client, a)
    assert r.status_code == 429 and "retry-after" in r.headers
    fs.upload_limiter._failures.clear()
    for _ in range(fs.MAX_CONCURRENT):
        assert fs._slots.acquire(blocking=False)
    try:
        r = _send(client, a)
        assert r.status_code == 503 and r.json()["code"] == "file_busy"
    finally:
        for _ in range(fs.MAX_CONCURRENT):
            fs._slots.release()


def test_file_is_removed_when_db_save_fails(client, family, monkeypatch, tmp_path):
    a, _, _ = family

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(fs.repo, "add_photo_message", boom)
    with pytest.raises(RuntimeError):
        _send(client, a)
    directory = Path(tmp_path) / "chat_files"
    assert not directory.exists() or list(directory.iterdir()) == []
