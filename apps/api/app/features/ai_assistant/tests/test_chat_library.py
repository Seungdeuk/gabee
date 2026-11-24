"""가족 전체방에 올린 문서가 가족 공유 문서함(knowledge)에 자동 등록된다: 가족방의 문서 첨부만(1:1 방·사진 제외), 지원하지 않는 형식은 등록하지 않고 민감 문서는 민감 표시를 붙여 등록하며,
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
from tests.helpers import allow_ai, join_family, signup

NOTICE = (
    "해솔초등학교 가정통신문\n2026년 11월 현장체험학습 안내\n11월 7일 오전 8시 40분 국립중앙박물관\n준비물: 도시락, 물\n"
).encode()
# 규칙(낱말 2개 이상)만으로 처방전으로 잡히는 글: 외부 분류에 기대지 않는다
PRESCRIPTION = (
    "서울약국 처방전\n환자 김가비\n처방의약품 아목시실린 투약일수 3일 용법 1일 3회 복용\n".encode()
)


class FakeOcr:
    def read(self, image):
        return [OcrLine("문서", 0.9)]


@pytest.fixture
def family(client, family, monkeypatch):
    """이 모듈의 가족은 기본으로 가족 AI 동의가 켜진 상태다(동의가 없으면 채팅 문서 등록을 보류한다, ADR 0024). 동의 없는 시험은 직접 끈다."""
    allow_ai(client, family[0], monkeypatch)
    return family


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


def test_a_document_sent_without_family_ai_consent_is_held_and_not_registered(client, family):
    """동의가 없으면 채팅 메시지·원본 첨부는 남지만 문서함 등록은 보류한다(로컬로만 가린 문서를 지식베이스에 넣지 않는다)."""
    a, _, group = family
    client.put("/family-chat/ai/settings", json={"enabled": False}, headers=a)
    msg = _send_file(client, a)
    assert msg["id"] and _items(group["id"]) == []


def test_the_chat_upload_creates_no_notification_for_the_new_document(client, family):
    """채팅 문서 자동 등록은 "새 문서" 알림을 포함해 알림 행을 하나도 만들지 않는다(문서 등록 알림은 없앴다)."""
    a, _, _ = family
    with SessionLocal() as db:
        before = len(db.scalars(select(Notification)).all())
    _send_file(client, a)
    with SessionLocal() as db:
        assert len(db.scalars(select(Notification)).all()) == before


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


def test_sensitive_documents_are_registered_and_flagged_sensitive(client, family, tmp_path):
    """가족 전체방에 올린 문서는 민감 문서(처방전 등)도 문서함에 들어간다(2026-11-09 사용자 결정). 기록에는 민감 표시가 붙는다."""
    a, _, group = family
    _send_file(client, a, data=PRESCRIPTION, name="처방전.txt")
    items = _items(group["id"])
    assert len(items) == 1 and items[0].sensitivity == "sensitive"
    assert _raw_files(tmp_path) != []  # 원본도 문서함의 다른 문서와 같게 보관한다


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


def test_deleting_the_message_while_it_is_being_registered_leaves_nothing_in_the_library(
    client, family, tmp_path, monkeypatch
):
    """읽는 도중(OCR·재시도 대기)에 메시지를 지우면, 처리가 끝난 뒤에도 지운 메시지의 문서가 문서함에 남지 않는다."""
    a, _, group = family
    queued = []
    monkeypatch.setattr(library, "_submit", lambda fn, *args: queued.append((fn, args)))
    msg = _send_file(client, a)
    assert _items(group["id"]) == [] and len(queued) == 1  # 아직 처리 전
    client.delete(f"/family-chat/messages/{msg['id']}", headers=a)  # 처리 전에 지운다
    fn, args = queued[0]
    fn(*args)
    assert _items(group["id"]) == [] and _raw_files(tmp_path) == []


def test_deleting_during_the_read_is_also_caught_right_after_saving(
    client, family, tmp_path, monkeypatch
):
    a, _, group = family
    queued = []
    monkeypatch.setattr(library, "_submit", lambda fn, *args: queued.append((fn, args)))
    msg = _send_file(client, a)
    original = files.ingest_service.ingest_file

    def delete_while_reading(*args, **kwargs):
        result = original(*args, **kwargs)
        client.delete(f"/family-chat/messages/{msg['id']}", headers=a)  # 읽는 사이에 지운다
        return result

    monkeypatch.setattr(files.ingest_service, "ingest_file", delete_while_reading)
    fn, args = queued[0]
    fn(*args)
    assert _items(group["id"]) == []  # 저장 직후 첨부가 없어진 것을 알고 되돌린다
    assert _raw_files(tmp_path) == []


def test_a_final_read_failure_leaves_no_original_or_record_behind(
    client, family, tmp_path, monkeypatch
):
    """Claude 연결이 계속 안 돼서 끝내 못 읽어도, 분류·가리기 전에 보관한 원본이 기록 없이 남지 않는다."""
    a, _, group = family
    monkeypatch.setattr(settings, "ingest_retry_max", 0)
    original = files.ingest_service.ingest_file

    def unavailable(*args, **kwargs):
        result = original(*args, **kwargs)  # 원본은 먼저 보관된다
        quality = result.quality.model_copy(update={"status": "failed", "error": "llm_unavailable"})
        return result.model_copy(update={"quality": quality})

    monkeypatch.setattr(files.ingest_service, "ingest_file", unavailable)
    _send_file(client, a)
    assert _items(group["id"]) == [] and _raw_files(tmp_path) == []
    with SessionLocal() as db:
        assert db.scalars(select(Photo)).all() == []


def test_an_unexpected_error_while_registering_leaves_no_original_behind(
    client, family, tmp_path, monkeypatch
):
    a, _, group = family

    def boom(result):
        raise RuntimeError("embedding model missing")

    monkeypatch.setattr(files.from_ingest, "to_item", boom)
    msg = _send_file(client, a)  # 전송은 그대로 성공한다
    assert msg["attachment"]["kind"] == "file"
    assert _items(group["id"]) == [] and _raw_files(tmp_path) == []
    with SessionLocal() as db:
        assert db.scalars(select(Photo)).all() == []


def test_a_medical_certificate_is_registered_from_the_chat(client, family, tmp_path, monkeypatch):
    """진단서처럼 이름만 민감한 문서도 가족 전체방에서 올리면 문서함에 들어간다(2026-11-09 사용자 결정)."""
    a, _, group = family
    original = files.from_ingest.to_item

    def as_certificate(result):
        return {**original(result), "kind_label": "진단서", "sensitivity": None}

    monkeypatch.setattr(files.from_ingest, "to_item", as_certificate)
    _send_file(client, a)
    items = _items(group["id"])
    assert len(items) == 1 and items[0].kind_label == "진단서"
    assert (
        items[0].sensitivity == "sensitive"
    )  # 이름만 민감한 문서도 민감 표시가 붙는다(@가비 제외 설정·AI 리포트 집계가 이 표시를 쓴다)
    assert _raw_files(tmp_path) != []


@pytest.mark.parametrize("kind", ["외국인등록증", "통장 사본", "소견서", "검사결과지"])
def test_documents_that_are_only_sensitive_by_name_are_flagged_sensitive(
    client, family, monkeypatch, kind
):
    a, _, group = family
    original = files.from_ingest.to_item
    monkeypatch.setattr(
        files.from_ingest,
        "to_item",
        lambda result: {**original(result), "kind_label": kind, "sensitivity": None},
    )
    _send_file(client, a)
    items = _items(group["id"])
    assert len(items) == 1 and items[0].sensitivity == "sensitive", kind


def test_reminders_are_not_planned_for_sensitive_chat_documents(client, family, monkeypatch):
    """챙길 일 뽑기(INGEST_REMINDERS)는 문서 본문을 Claude 로 보내므로, 민감 문서는 건너뛴다. 일반 문서는 그대로 뽑는다."""
    a, _, group = family
    monkeypatch.setattr(settings, "ingest_reminders", True)
    planned: list[str] = []
    monkeypatch.setattr(files.reminders, "plan", lambda db, gid, uid, pid: planned.append(pid))
    client.put("/family-chat/ai/settings", json={"enabled": False}, headers=a)
    _send_file(client, a)  # 일반 문서지만 가족 AI 동의가 없다: 등록 자체를 보류한다
    assert _items(group["id"]) == [] and planned == []  # 동의 없이는 본문을 Claude 로 보내지 않는다
    allow_ai(client, a, monkeypatch)
    _send_file(client, a, data=PRESCRIPTION, name="처방전.txt")
    assert (
        len(_items(group["id"])) == 1 and planned == []
    )  # 민감 문서는 동의해도 외부로 보내지 않는다
    _send_file(client, a)  # 일반 문서
    assert len(planned) == 1 and len(_items(group["id"])) == 2
