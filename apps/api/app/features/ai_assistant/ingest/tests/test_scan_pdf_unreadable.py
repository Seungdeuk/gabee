# ruff: noqa: F811
"""글자 층이 없는 스캔 PDF 를 읽을 수단이 없을 때(Claude 읽기 꺼짐 또는 동의 없음)의 계약.

- 읽은 글이 하나도 없으면 **실패**(사진과 같은 코드: `ocr_unavailable`·`consent_required`)이고, 내용 없는 "읽지 못한 부분" 자리표시를 정상 기록으로 만들지 않는다.
  내용 없는 자리표시 글을 가리기·분류·챙길 일(외부 AI)로 보내지도 않는다.
- 글자 층이 있는 쪽이 하나라도 있으면 기존 계약 그대로다: 있는 글을 쓰고 읽지 못한 스캔 쪽은 노트(`partial`)로 알린다.
- 글자 층이 있는 텍스트 PDF 는 영향이 없다.
외부 AI 는 호출되면 실패하는 대역이다(실제 호출·개인정보 없음, 합성 데이터)."""

import pytest

from app.features.ai_assistant.ingest import llm_ingest
from app.features.ai_assistant.ingest.service import preprocess
from app.features.ai_assistant.ingest.tests.test_external_consent import (  # noqa: F401
    Sent,
    claude_on_but_trapped,
    pdf,
)
from app.shared.config import settings

TEXT = "Hello family notice about the school trip next week"


def test_all_scan_pdf_with_claude_reading_off_fails_and_sends_nothing(
    claude_on_but_trapped, monkeypatch
):
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)  # 읽을 로컬 OCR 도 없다
    r = preprocess(pdf(["", ""]), "s.pdf", external=True)
    assert r.quality.status == "failed" and r.quality.error == "ocr_unavailable"
    assert "INGEST_LLM_OCR" in r.quality.warnings[0]
    assert r.content.text == ""  # 가리기·분류가 불린다면 trap 이 Sent 로 터진다(불리지 않았다)


def test_all_scan_pdf_without_consent_fails_as_consent_required_and_sends_nothing(
    claude_on_but_trapped,
):
    r = preprocess(pdf([""]), "s.pdf", external=False)
    assert r.quality.status == "failed" and r.quality.error == "consent_required"


def test_empty_placeholder_text_is_never_masked_when_the_pdf_is_unreadable(
    claude_on_but_trapped, monkeypatch
):
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)
    calls = []
    monkeypatch.setattr(llm_ingest, "mask", lambda *a, **k: calls.append(a) or ("", {}, "none"))
    preprocess(pdf([""]), "s.pdf", external=True)
    assert calls == []


def test_a_pdf_with_some_text_keeps_the_documented_partial_behavior(
    claude_on_but_trapped, monkeypatch
):
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)
    monkeypatch.setattr(
        settings, "ingest_llm_mask", False
    )  # 가리기 대역이 터지지 않게(이 시험은 읽기 계약만 본다)
    r = preprocess(pdf([TEXT, ""]), "m.pdf", external=True)
    assert r.quality.status == "partial" and TEXT in r.content.text
    assert any("스캔" in w and "읽지 못했어요" in w for w in r.quality.warnings)


@pytest.mark.parametrize("llm_ocr", [True, False])
def test_a_text_pdf_is_unaffected(claude_on_but_trapped, monkeypatch, llm_ocr):
    monkeypatch.setattr(settings, "ingest_llm_ocr", llm_ocr)
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    if llm_ocr:
        monkeypatch.setattr(llm_ingest, "ocr_pdf", lambda data: (TEXT, None))
    r = preprocess(pdf([TEXT]), "t.pdf", external=True)
    assert r.quality.status == "ok" and TEXT in r.content.text
