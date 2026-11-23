"""가족 AI 동의가 없으면(`external=False`) 어떤 갈래도 Claude 로 보내지 않는다: 사진 읽기·PDF 스캔 쪽 읽기·글 가리기·PPT 그림 설명·분류.
글자를 외부로 보낸 뒤 가리는 것으로는 동의 문제가 풀리지 않으므로, 보내기 **전에** 막는지를 본다(Claude 호출 함수를 호출되면 실패하는 대역으로 바꾼다).
합성 데이터만 쓴다. 로컬 OCR(RapidOCR)은 서비스에 없다: 이 파일은 그것을 import 하지 않는 것도 확인한다."""

import ast
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

from app.features.ai_assistant.ingest import classify as classify_mod
from app.features.ai_assistant.ingest import doc_classifier, figures, llm_ingest
from app.features.ai_assistant.ingest.converters import OcrLine
from app.features.ai_assistant.ingest.service import ingest_file, preprocess
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


# ---------- 2026-11-23 보완: 기본값은 fail-closed, 외부 전송 직전 재확인, 호출처 점검 ----------


def test_the_service_entry_points_require_the_external_flag():
    """`external` 은 필수 인자다: 빠뜨리면 동의를 조용히 우회하는 대신 TypeError 로 드러난다."""
    with pytest.raises(TypeError):
        preprocess(b"hello", "a.txt")
    with pytest.raises(TypeError):
        ingest_file("g", b"hello", "a.txt")


def test_lower_level_helpers_default_to_not_sending(claude_on_but_trapped):
    """값을 넘기지 않은 하위 함수는 외부로 보내지 않는다(기본 False)."""
    from app.features.ai_assistant.ingest import service

    masked, privacy = service._mask(
        "연락처 010-1234-5678"
    )  # 가리기 Claude 설정이 켜져 있어도 로컬 규칙이다
    assert "1234-5678" not in masked
    assert figures.describe_pptx(b"x", "본문") == ("본문", None)  # 그림을 읽으러 가지 않는다
    r = preprocess(b"zzz qqq vvv", "a.txt", external=False)
    assert (
        classify_mod.classify(r) is not None
    )  # 기본값: Jev 를 부르지 않는다(대역이 호출되면 실패한다)
    assert (
        service._read_pdf(pdf(["Hello family notice about the school trip next week", ""]), None)[1]
        is not None
    )


def test_an_injected_jev_is_not_called_without_consent(claude_on_but_trapped, monkeypatch):
    monkeypatch.setattr(doc_classifier, "predict", lambda text: None)
    r = preprocess(b"zzz qqq vvv", "a.txt", external=False)
    calls = []

    def injected(state, questions):
        calls.append(1)
        return {}

    classify_mod.classify(r, jev=injected, external=False)
    assert calls == []  # 끼워 준 Jev 도 동의 없이는 부르지 않는다
    classify_mod.classify(r, jev=injected, external=True)
    assert calls  # 대조군


def test_recheck_blocks_a_photo_when_consent_was_withdrawn_just_before_sending(monkeypatch):
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    monkeypatch.setattr(
        llm_ingest, "ocr_image", lambda image: (_ for _ in ()).throw(Sent("보내면 안 된다"))
    )
    r = preprocess(png(), "a.png", external=True, recheck=lambda: False)
    assert r.quality.status == "failed" and r.quality.error == "consent_required"


def test_recheck_blocks_only_the_steps_after_the_withdrawal(monkeypatch):
    """읽기(이미 나간 호출)는 끝났고 그 뒤 동의가 철회되면, 가리기는 로컬 규칙으로 한다."""
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    monkeypatch.setattr(settings, "ingest_llm_mask", True)
    seen = {"read": 0, "mask": 0}

    def read(image):
        seen["read"] += 1
        return doc_ai.OcrOut("연락처 010-1234-5678 로 알려 주세요", False, 0, 0)

    def mask(text, family=None):
        seen["mask"] += 1
        return text, {}, "none"

    monkeypatch.setattr(llm_ingest, "ocr_image", read)
    monkeypatch.setattr(llm_ingest, "mask", mask)
    answers = iter([True, False])  # 읽기 직전은 동의 있음, 가리기 직전은 철회됨
    r = preprocess(png(), "a.png", external=True, recheck=lambda: next(answers))
    assert seen == {"read": 1, "mask": 0}
    assert (
        r.quality.status in ("ok", "partial") and "1234-5678" not in r.content.text
    )  # 로컬 규칙이 가렸다


def test_every_production_call_passes_external_explicitly():
    """운영 코드가 `ingest_file`·`preprocess`·`classify`·`describe_pptx` 를 부를 때 `external=` 를 반드시 넘긴다(새 호출자가 빠뜨리면 이 시험이 막는다)."""
    app = Path(__file__).resolve().parents[5] / "app"
    watched = {"ingest_file", "preprocess", "classify", "describe_pptx"}
    scope = [
        app / "features" / "ai_assistant" / "files.py",
        *(app / "features" / "ai_assistant" / "ingest").glob("*.py"),
    ]
    missing, inspected = [], 0
    for path in scope:
        if path.name in {
            "siglip_margin.py",
            "photo_judge.py",
        }:  # 이름만 같은 다른 함수(이미지 전처리)
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            if name in watched:
                inspected += 1
            if name in watched and not any(k.arg == "external" for k in node.keywords):
                missing.append(f"{path.name}:{node.lineno} {name}(")
    assert inspected >= 4, (
        inspected
    )  # files.py 의 ingest_file, service.py 의 preprocess·classify·describe_pptx 를 실제로 봤다(공허한 통과 방지)
    assert missing == [], missing
    # 다른 기능이 `ingest_file` 을 직접 부르지 않는다(`files.process_file` 하나만 거친다)
    for path in app.rglob("*.py"):
        if "tests" in path.parts or path.name == "files.py" and path.parent.name == "ai_assistant":
            continue
        if path.parts[-2] == "ingest" and path.name == "service.py":
            continue
        assert "ingest_file(" not in path.read_text(encoding="utf-8"), path


# ---------- require_external: 로컬 규칙으로 대신하지 않고 멈춘다(가족 채팅방 자동 처리) ----------


@pytest.mark.parametrize(
    "name, data",
    [
        ("a.txt", b"Please bring the green notebook tomorrow morning thank you very much"),
        ("n.pdf", pdf(["Hello family notice about the school trip next week"])),
        ("p.png", png()),
    ],
)
def test_require_external_without_consent_fails_instead_of_masking_locally(
    claude_on_but_trapped, name, data
):
    out = preprocess(data, name, external=False, require_external=True)
    assert out.quality.status == "failed" and out.quality.error == "consent_required"
    assert out.content.text == ""  # 로컬로만 가린 글을 만들지 않는다


def test_require_external_with_consent_revoked_before_the_send_stops_without_sending(monkeypatch):
    monkeypatch.setattr(settings, "ingest_llm_ocr", True)
    monkeypatch.setattr(settings, "ingest_llm_mask", True)
    sent = []
    monkeypatch.setattr(
        llm_ingest, "mask", lambda text, family=None: sent.append(text) or (text, {}, False)
    )
    out = preprocess(
        b"Please bring the green notebook tomorrow morning thank you very much",
        "a.txt",
        external=True,  # 처리 시작 때는 동의가 있었지만
        recheck=lambda: False,  # 보내기 직전 재확인에서 철회가 확인됐다
        require_external=True,
    )
    assert out.quality.error == "consent_required" and sent == []


def test_without_require_external_the_local_fallback_is_unchanged(claude_on_but_trapped):
    """메인 AI·기존 시험이 쓰는 기본값(False): 동의가 막은 단계는 로컬 규칙으로 대신한다(기존 동작 유지)."""
    out = preprocess(
        b"Please bring the green notebook tomorrow morning thank you very much",
        "a.txt",
        external=False,
    )
    assert out.quality.status != "failed"
