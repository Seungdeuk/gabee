# ruff: noqa: F811
"""B안(PR #520 병합, `PHOTO_CLASSIFY_SIGLIP=false`) 출시 점검용 보완 시험 — 기존 시험이 직접 확인하지 않던 `INGEST_LLM_OCR=false`(읽을 로컬 OCR 이 없음) 상태.

관찰한 실제 동작을 그대로 고정한다(약화·우회 없음):
- 메인 AI 직접 업로드 사진: 읽을 수단이 없어 `failed` 로 끝나고 외부 AI 호출·문서함 등록이 없다.
- 글자 층이 없는 스캔 PDF(메인 AI·가족 채팅방 모두): 읽기(ocr_pdf·ocr_image) 호출이 없고, 내용 없는 "읽지 못한 부분" 자리표시 항목(`has_unread_parts`, `needs_review`)만 만들어진다.
  자리표시 항목에도 가리기·챙길 일 대역이 1회 불리는 것을 관찰했다(내용 없는 자리표시 글만 넘어간다). 이것이 의도인지는 별도 확인 대상이다.
- 가족 채팅방 사진은 스위치 OFF 라 등록되지 않는다.
외부 AI 는 호출 횟수를 세는 대역이다(실제 호출·실제 개인정보 없음, 합성 데이터)."""

from app.features.ai_assistant.tests.test_consent_ingest_flow import (  # noqa: F401  (픽스처·도우미 재사용)
    _chat_file,
    _consent,
    _isolated,
    _items,
    _main_upload,
    _send_photo,
    _status,
    claude,
    family,
    pdf,
    png,
)
from app.shared.config import settings


def test_main_ai_photo_upload_fails_safely_when_claude_reading_is_off(
    client, family, claude, monkeypatch
):
    a, _, group = family
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)
    fid = _main_upload(client, a, "p.png", png(), "image/png")
    assert _status(client, a, fid) == "failed"
    assert claude.total() == 0  # 읽기·가리기·분류·챙길 일 어느 외부 호출도 없다
    assert _items(group["id"]) == []  # 문서함에도 들어가지 않는다


def test_main_ai_scan_only_pdf_with_claude_reading_off_is_an_empty_placeholder_not_invented_text(
    client, family, claude, monkeypatch
):
    a, _, group = family
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)
    fid = _main_upload(
        client, a, "s.pdf", pdf([""]), "application/pdf"
    )  # 글자 층이 없는 스캔 쪽만 있는 PDF
    assert _status(client, a, fid) == "needs_review"
    assert claude.calls["ocr_pdf"] == 0 and claude.calls["ocr_image"] == 0  # 읽으러 가지 않는다
    assert claude.calls["jev"] == 0 and claude.calls["figure"] == 0
    (item,) = _items(group["id"])
    assert item.has_unread_parts is True and len(item.body_md) < 80  # 내용 없는 자리표시


def test_family_room_with_reading_and_photo_switch_off_registers_only_an_empty_placeholder(
    client, family, claude, monkeypatch
):
    a, _, group = family
    _consent(client, a, True)
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)
    monkeypatch.setattr(settings, "photo_classify_siglip", False)  # B안: 사진 판별 스위치 OFF
    _send_photo(client, a)
    _chat_file(client, a, "s.pdf", pdf([""]), "application/pdf")
    (item,) = _items(group["id"])  # 사진은 등록되지 않고, 스캔 PDF 는 자리표시 하나뿐이다
    assert item.has_unread_parts is True and len(item.body_md) < 80
    assert claude.calls["ocr_pdf"] == 0 and claude.calls["ocr_image"] == 0
    assert claude.calls["jev"] == 0 and claude.calls["figure"] == 0
