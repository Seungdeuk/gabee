"""`INGEST_LLM_MASK=false` 이면 가족 채팅 문서·사진을 AI 문서함에 등록하지 않는다(fail-closed).

결함: Claude 가리기가 꺼져 있으면 로컬 규칙(주민번호 등만 가림)만 적용돼 이름·주소·전화번호가 남은 채팅 문서가 등록되고, 그것이 @가비 검색으로 Claude 에 전송됐다.
이 시험은 등록 진입점 세 곳(자동 문서·자동 사진·수동 "문서로 저장")이 가리기가 꺼져 있을 때 읽기·저장·외부 호출을 시작하지 않고 판별 상태도 바꾸지 않음을 확인한다.
가리기가 켜져 있으면(기본값) 기존 동작 그대로임도 확인한다. 메인 AI 직접 업로드는 이 경로가 아니라 영향이 없다. 외부 AI 는 대역이고 데이터는 합성이다."""

import pytest

from app.features.ai_assistant import files, library
from app.features.family_chat.models import ChatPhotoCheck
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.llm import client as llm


@pytest.fixture(autouse=True)
def _no_outside_world(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("가리기가 꺼져 있으면 외부 호출·읽기를 시작하면 안 돼요")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.setattr(llm, "complete", boom)


@pytest.fixture
def started(monkeypatch):
    """읽기·저장이 시작됐는지 센다(시작되면 기록)."""
    calls = []
    # 첨부가 살아 있고 아직 등록 전인 상태로 만든다: 가드가 없으면 시험이 읽기·저장 단계까지 실제로 가도록(첨부 행이 없어서 중간에 멈추는 약한 시험이 되지 않게)
    monkeypatch.setattr(library.chat_library, "attachment_exists", lambda *a, **k: True)
    monkeypatch.setattr(library.knowledge_repo, "get_by_attachment", lambda *a, **k: None)
    monkeypatch.setattr(files, "process_file", lambda *a, **k: calls.append("process_file"))
    monkeypatch.setattr(
        library.service,
        "receive_file",
        lambda *a, **k: calls.append("receive") or type("P", (), {"id": "p1"})(),
    )
    return calls


def test_chat_document_is_not_registered_when_masking_is_off(monkeypatch, started):
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    library.register_chat_document("g1", "u1", "att1", "a.txt", "text/plain", b"hello")
    assert started == []  # 받기·읽기·저장·외부 호출 모두 시작하지 않았다


def test_chat_photo_is_not_judged_or_registered_when_masking_is_off(monkeypatch, started):
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    monkeypatch.setattr(
        library,
        "_judge_photo",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("판별도 시작하지 않는다")),
    )
    library.register_chat_photo("g1", "u1", "att1", b"x", False)
    library.register_chat_photo("g1", "u1", "att1", b"x", True)  # 직접 저장 요청이어도 같다
    assert started == []


def test_manual_save_to_library_is_503_and_changes_no_state_when_masking_is_off(
    client, family, monkeypatch
):
    import io

    from PIL import Image

    a, _, _ = family
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 120, 200)).save(buf, format="JPEG")
    up = client.post(
        "/family-chat/photos", files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")}, headers=a
    )
    assert up.status_code == 201, up.text
    att = up.json()["attachment"]["id"]
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    with SessionLocal() as db:
        before = db.get(ChatPhotoCheck, att).status
    r = client.post(f"/family-chat/photos/{att}/library", headers=a)
    assert r.status_code == 503 and r.json()["code"] == "masking_unavailable"
    with SessionLocal() as db:
        assert db.get(ChatPhotoCheck, att).status == before  # 문서(수동)로 바뀌지 않았다
