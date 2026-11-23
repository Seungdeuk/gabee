"""가족 AI 동의가 없으면(`external=False`) 어떤 갈래도 Claude 로 보내지 않는다: 사진 읽기·PDF 스캔 쪽 읽기·글 가리기·PPT 그림 설명·분류.
글자를 외부로 보낸 뒤 가리는 것으로는 동의 문제가 풀리지 않으므로, 보내기 **전에** 막는지를 본다(Claude 호출 함수를 호출되면 실패하는 대역으로 바꾼다).
합성 데이터만 쓴다. 로컬 OCR(RapidOCR)은 서비스에 없다: 이 파일은 그것을 import 하지 않는 것도 확인한다."""

import io
import sys

import pytest
from PIL import Image

from app.features.ai_assistant.ingest import classify as classify_mod
from app.features.ai_assistant.ingest import doc_classifier, figures, llm_ingest
from app.features.ai_assistant.ingest.converters import OcrLine
from app.features.ai_assistant.ingest.service import preprocess
from app.shared.config import settings
from app.shared.llm import doc_ai, jev


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (240, 240, 240)).save(buf, "PNG")
    return buf.getvalue()


def pdf(pages) -> bytes:
    """글자 층이 있는 최소 PDF(영문만). 빈 문자열이면 글자 없는 쪽(스캔 쪽 대역)."""
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        None,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>"
        )
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


class Sent(Exception):
    """Claude 로 보내려는 호출이 일어났다(동의가 없으면 일어나면 안 된다)."""


@pytest.fixture
def claude_on_but_trapped(monkeypatch):
    """서비스 기본 설정(Claude 로 읽고 가린다)을 켜고, Claude 로 가는 모든 함수를 호출되면 실패하는 대역으로 바꾼다."""
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    monkeypatch.setattr(settings, "ingest_llm_mask", True)

    def trap(*args, **kwargs):
        raise Sent("외부 AI 로 보내면 안 된다")

    for name in ("ocr_image", "ocr_pdf", "mask"):
        monkeypatch.setattr(llm_ingest, name, trap)
    monkeypatch.setattr(doc_ai, "describe_figure", trap)
    monkeypatch.setattr(jev, "ask", trap)
    monkeypatch.setattr(jev, "available", lambda: True)


def test_without_consent_a_photo_is_not_read_and_nothing_is_sent(claude_on_but_trapped):
    r = preprocess(png(), "a.png", external=False)
    assert r.quality.status == "failed" and r.quality.error == "consent_required"
    assert "동의" in r.quality.warnings[0]


def test_with_consent_a_photo_is_read_by_claude(monkeypatch):
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    monkeypatch.setattr(settings, "ingest_llm_mask", False)
    seen = []

    def read(image):
        seen.append(image)
        return doc_ai.OcrOut("가정통신문\n현장체험학습 안내", False, 1, 1)

    monkeypatch.setattr(llm_ingest, "ocr_image", read)
    r = preprocess(png(), "a.png", external=True)
    assert (
        r.quality.status in ("ok", "partial") and "가정통신문" in r.content.text and len(seen) == 1
    )


def test_without_consent_a_text_pdf_is_read_locally_and_never_sent(claude_on_but_trapped):
    r = preprocess(
        pdf(["Hello family notice about the school trip next week"]), "a.pdf", external=False
    )
    assert (
        r.quality.status == "ok"
        and "Hello family notice about the school trip next week" in r.content.text
    )


def test_without_consent_scanned_pdf_pages_are_left_unread_with_a_note(claude_on_but_trapped):
    r = preprocess(
        pdf(["Hello family notice about the school trip next week", ""]), "a.pdf", external=False
    )
    assert r.quality.status == "partial"
    assert any("동의" in w for w in r.quality.warnings)  # 이유를 알려 준다
    assert "Hello family notice about the school trip next week" in r.content.text


def test_without_consent_text_is_masked_by_local_rules_not_by_claude(claude_on_but_trapped):
    r = preprocess("연락처 010-1234-5678 로 알려 주세요".encode(), "a.txt", external=False)
    assert r.quality.status == "ok" and "1234-5678" not in r.content.text  # 로컬 규칙이 가렸다


def test_without_consent_the_default_classifier_jev_is_not_used(claude_on_but_trapped, monkeypatch):
    monkeypatch.setattr(doc_classifier, "predict", lambda text: None)  # 규칙·분류기로 못 정하는 글
    r = preprocess(b"zzz qqq vvv", "a.txt", external=False)
    c = classify_mod.classify(r, external=False)
    assert c is not None and c.by != "jev"  # 사람 확인으로 남는다
    with pytest.raises(
        Sent
    ):  # 동의가 있으면 같은 글을 Jev 로 보낸다(대역이 막는다) — 위 호출이 우연히 안 보낸 것이 아님을 보인다
        classify_mod.classify(r, external=True)


def test_without_consent_pptx_pictures_are_not_described(monkeypatch):
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)

    def boom(data):
        raise Sent("그림을 읽으러 가면 안 된다")

    monkeypatch.setattr(figures, "pptx_pictures", boom)
    assert figures.describe_pptx(b"x", "본문", external=False) == ("본문", None)
    with pytest.raises(Sent):
        figures.describe_pptx(b"x", "본문", external=True)


def test_a_photo_without_any_reader_fails_clearly_when_claude_reading_is_off(monkeypatch):
    """서비스에는 로컬 OCR 이 없다: INGEST_LLM_OCR 를 끄고 읽기 구성 요소도 없으면 사진은 읽을 수단이 없어 실패한다."""
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)
    r = preprocess(png(), "a.png", external=True)
    assert r.quality.status == "failed" and r.quality.error == "ocr_unavailable"


def test_the_local_ocr_package_is_never_imported(monkeypatch):
    """rapidocr 를 import 하면 실패하게 막아도(= 의존성을 뺀 서버) 읽기 구성 요소를 끼운 경로가 그대로 돈다."""
    monkeypatch.setitem(sys.modules, "rapidocr", None)
    monkeypatch.setattr(settings, "ingest_llm_ocr", False)

    class Reader:
        def read(self, image):
            return [OcrLine("가정통신문", 0.95), OcrLine("현장체험학습 안내", 0.95)]

    r = preprocess(png(), "a.png", ocr=Reader(), external=True)
    assert r.quality.status in ("ok", "partial") and "가정통신문" in r.content.text
