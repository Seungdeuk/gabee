# ruff: noqa: F811
"""B안(PR #520 병합, `PHOTO_CLASSIFY_SIGLIP=false`) 출시 점검용 보완 시험 — `INGEST_LLM_OCR=false`(읽을 로컬 OCR 이 없음) 상태.

- 메인 AI 직접 업로드 사진·글자 층 없는 스캔 PDF: 읽을 수단이 없어 `failed` 로 끝나고 외부 AI 호출(읽기·가리기·분류·챙길 일)과 문서함 등록이 없다.
  (이전에는 스캔 PDF 가 내용 없는 "읽지 못한 부분" 자리표시 항목으로 등록되고 가리기·챙길 일 처리가 불렸다 — 수정함, 상세는 test_scan_pdf_unreadable.py)
- 가족 채팅방: 사진은 스위치 OFF 라 등록되지 않고, 스캔 PDF 는 등록되지 않으며 채팅 원본 첨부만 남는다(외부 호출 없음).
- 글자 층이 있는 PDF 는 이 상태에서도 정상 등록된다(가리기 포함, 기존 계약).
외부 AI 는 호출 횟수를 세는 대역이다(실제 호출·실제 개인정보 없음, 합성 데이터)."""

from app.features.ai_assistant.tests.test_consent_ingest_flow import (  # noqa: F401  (픽스처·도우미 재사용)
    PLAIN_TEXT,
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


def test_main_ai_scan_only_pdf_with_claude_reading_off_fails_without_any_external_call(
    client, family, claude, monkeypatch
):
    a, _, group = family
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)
    fid = _main_upload(
        client, a, "s.pdf", pdf([""]), "application/pdf"
    )  # 글자 층이 없는 스캔 쪽만 있는 PDF
    assert _status(client, a, fid) == "failed"
    assert claude.total() == 0  # 자리표시 글도 가리기·챙길 일로 보내지 않는다
    assert _items(group["id"]) == []


def test_main_ai_text_pdf_with_claude_reading_off_is_still_registered(
    client, family, claude, monkeypatch
):
    a, _, group = family
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)
    fid = _main_upload(client, a, "t.pdf", pdf([PLAIN_TEXT]), "application/pdf")
    assert _status(client, a, fid) in ("analyzed", "needs_review")
    assert claude.calls["ocr_pdf"] == 0 and claude.calls["ocr_image"] == 0  # 글자 층만 쓴다
    (item,) = _items(group["id"])
    assert "green notebook" in item.body_md


def test_family_room_scan_pdf_and_photo_with_reading_and_photo_switch_off_register_nothing(
    client, family, claude, monkeypatch
):
    a, _, group = family
    _consent(client, a, True)
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)
    monkeypatch.setattr(settings, "photo_classify_siglip", False)  # B안: 사진 판별 스위치 OFF
    _send_photo(client, a)
    _chat_file(client, a, "s.pdf", pdf([""]), "application/pdf")
    assert _items(group["id"]) == []  # 사진·스캔 PDF 모두 문서함에 들어가지 않는다
    assert claude.total() == 0  # 가리기·분류·챙길 일 포함 외부 호출 없음
