"""가족 전체방에 올린 문서가 가족 공유 문서함(knowledge)에 자동 등록된다: 가족방의 문서 첨부만(1:1 방·사진 제외), 민감 문서와 지원하지 않는 형식은 등록하지 않고,
같은 첨부는 한 번만, 채팅 메시지를 지우면 연결된 기록도 함께 지워지고, 등록이 실패해도 채팅 전송은 그대로다. 모델이나 인터넷 없이 돈다."""

import io
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app.features.ai_assistant import files, library
from app.features.ai_assistant.ingest.converters import OcrLine
from app.features.ai_assistant.knowledge.models import KnowledgeItem
from app.features.ai_assistant.models import Photo
from app.features.family_chat import file_service, photo_service
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.notifications import Notification
from tests.helpers import join_family, signup

NOTICE = (
    "해솔초등학교 가정통신문\n2026년 11월 현장체험학습 안내\n11월 7일 오전 8시 40분 국립중앙박물관\n준비물: 도시락, 물\n"
).encode()
PRESCRIPTION = "서울약국 처방전\n환자 김가비\n2026-11-05 처방 내용 아목시실린 3일분\n".encode()


class FakeOcr:
    def read(self, image):
        return [OcrLine("문서", 0.9)]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """파일은 임시 폴더에, 등록은 스레드 대신 그 자리에서, OCR 은 가짜로."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    file_service.upload_limiter._failures.clear()
    photo_service.upload_limiter._failures.clear()
    monkeypatch.setattr(library, "_submit", lambda fn, *args: fn(*args))
    old = files.processors
    files.processors = files.Processors(ocr=FakeOcr())
    yield
    files.processors = old


def _me(client, headers) -> str:
    return client.get("/family-group/me", headers=headers).json()["id"]


def _send_file(
    client, headers, data=NOTICE, name="가정통신문.txt", room_id=None, ctype="text/plain"
):
    r = client.post(
        "/family-chat/files",
        files={"file": (name, data, ctype)},
        data={"room_id": room_id} if room_id else None,
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _items(group_id=None):
    with SessionLocal() as db:
        q = select(KnowledgeItem)
        if group_id:
            q = q.where(KnowledgeItem.group_id == group_id)
        return list(db.scalars(q))


def _raw_files(tmp_path) -> list[Path]:
    raw = Path(tmp_path) / "raw"
    return [p for p in raw.rglob("*") if p.is_file()] if raw.exists() else []


def test_a_document_sent_to_the_family_room_is_registered_in_the_library(client, family, tmp_path):
    a, b, group = family
    msg = _send_file(client, a)
    items = _items(group["id"])
    assert len(items) == 1
    item = items[0]
    assert item.source_attachment_id == msg["attachment"]["id"]  # 채팅 첨부와 기록이 연결된다
    assert item.created_by == _me(client, a) and item.sensitivity == "normal"
    # 가족 누구나 문서함(기록 목록)에서 본다
    listed = client.get("/ai-assistant/knowledge/items", headers=b).json()
    assert [row["id"] for row in listed] == [item.id]
    with SessionLocal() as db:
        assert db.get(Photo, item.id).status in (
            "analyzed",
            "needs_review",
        )  # 처리 상태도 같은 방식으로 남는다
    assert len(_raw_files(tmp_path)) == 1  # 원본은 한 번 보관된다


def test_the_chat_upload_does_not_also_announce_a_new_document(client, family):
    """채팅에 이미 올라온 파일이라 "새 문서가 올라왔어요" 알림을 한 번 더 보내지 않는다."""
    a, _, _ = family
    _send_file(client, a)
    with SessionLocal() as db:
        assert (
            db.scalars(select(Notification).where(Notification.event == "document_added")).all()
            == []
        )


def test_documents_in_one_to_one_rooms_are_not_registered(client, family):
    a, b, group = family
    room = client.post(
        "/family-chat/rooms/direct", json={"user_id": _me(client, b)}, headers=a
    ).json()
    _send_file(client, a, room_id=room["id"])
    assert _items(group["id"]) == []  # 1:1 방 자료가 가족 전체의 문서함으로 새지 않는다


def test_photos_are_not_registered_automatically(client, family):
    a, _, group = family
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, format="JPEG")
    r = client.post(
        "/family-chat/photos", files={"file": ("a.jpg", out.getvalue(), "image/jpeg")}, headers=a
    )
    assert r.status_code == 201, r.text
    assert _items(group["id"]) == []  # 사진은 "문서로 저장"을 눌렀을 때만


def test_sensitive_documents_are_not_registered_and_leave_nothing_behind(client, family, tmp_path):
    a, _, group = family
    _send_file(client, a, data=PRESCRIPTION, name="처방전.txt")
    assert _items(group["id"]) == []
    with SessionLocal() as db:
        assert db.scalars(select(Photo)).all() == []  # 처리 기록도 남기지 않는다
    assert _raw_files(tmp_path) == []  # 가리기 전 원본 사본도 남기지 않는다


def test_unsupported_formats_are_not_registered(client, family, tmp_path):
    a, _, group = family
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64  # 예전 한글·워드·엑셀 형식
    _send_file(client, a, data=ole, name="안내문.hwp", ctype="application/x-hwp")
    assert _items(group["id"]) == []
    assert _raw_files(tmp_path) == []


def test_the_same_attachment_is_registered_only_once(client, family):
    a, _, group = family
    msg = _send_file(client, a)
    att = msg["attachment"]["id"]
    library.register_chat_document(
        group["id"], _me(client, a), att, "가정통신문.txt", "text/plain", NOTICE
    )
    library.register_chat_document(
        group["id"], _me(client, a), att, "가정통신문.txt", "text/plain", NOTICE
    )
    assert len(_items(group["id"])) == 1  # 다시 불려도(재시도·중복 요청) 한 건
    with SessionLocal() as db:
        assert len(db.scalars(select(Photo)).all()) == 1


def test_same_file_sent_twice_makes_two_records_but_one_original(client, family, tmp_path):
    a, _, group = family
    _send_file(client, a)
    _send_file(client, a)
    assert len(_items(group["id"])) == 2  # 메시지(첨부)마다 한 건
    assert len(_raw_files(tmp_path)) == 1  # 같은 내용의 원본은 한 번만 보관


def test_deleting_the_chat_message_removes_the_library_record_and_original(
    client, family, tmp_path
):
    a, b, group = family
    msg = _send_file(client, a)
    assert len(_items(group["id"])) == 1
    r = client.delete(f"/family-chat/messages/{msg['id']}", headers=a)
    assert r.status_code == 200, r.text
    assert _items(group["id"]) == []  # 연결된 문서함 기록도 함께 지워진다
    with SessionLocal() as db:
        assert db.scalars(select(Photo)).all() == []
    assert _raw_files(tmp_path) == []  # 보관한 원본도(다른 기록이 쓰지 않으면)
    assert client.get("/ai-assistant/knowledge/items", headers=b).json() == []


def test_deleting_one_of_two_messages_with_the_same_file_keeps_the_other_and_the_original(
    client, family, tmp_path
):
    a, _, group = family
    first = _send_file(client, a)
    _send_file(client, a)
    client.delete(f"/family-chat/messages/{first['id']}", headers=a)
    assert len(_items(group["id"])) == 1
    assert len(_raw_files(tmp_path)) == 1  # 아직 쓰는 기록이 있으니 원본은 그대로


def test_other_families_never_see_the_registered_document(client, family, other_family):
    a, _, group = family
    _send_file(client, a)
    listed = client.get("/ai-assistant/knowledge/items", headers=other_family).json()
    assert listed == []
    assert len(_items(group["id"])) == 1


def test_a_failing_registration_never_breaks_sending_the_file(client, family, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("library down")

    monkeypatch.setattr(library, "register_chat_document", boom)
    a, _, group = family
    msg = _send_file(client, a)  # 전송은 201 그대로
    assert msg["attachment"]["kind"] == "file"
    assert _items(group["id"]) == []


def test_documents_from_a_member_of_another_family_group_are_scoped_to_that_group(
    client, family, other_family
):
    a, _, group = family
    other_group_id = client.get("/family-group/groups/me", headers=other_family).json()["id"]
    _send_file(client, a)
    assert _items(other_group_id) == []  # 다른 가족 그룹에는 아무것도 생기지 않는다


def test_new_member_documents_register_under_the_family_group(client, family):
    a, _, group = family
    c = signup(client, "삼촌")
    assert join_family(client, a, group["invite_code"], c).status_code == 200
    _send_file(client, c)
    [item] = _items(group["id"])
    assert item.created_by == _me(client, c)
