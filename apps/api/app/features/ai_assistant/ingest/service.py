"""원본 전처리: 원본 보관 → 검사 → 형식별 글자 추출 → 개인정보 가리기 → 블록(번호 붙임)으로 정리.

    파일 ─▶ 원본 데이터 센터(그대로 보관) ─▶ 검사(빈 파일·용량) ─▶ 형식 판별
          ─┬─ 사진 ──────── 회전·축소·흑백 ─▶ OCR ─▶ 줄 목록
           ├─ PDF·PPT·엑셀·워드 ─ MarkItDown ─▶ 마크다운 (쪽·슬라이드·시트 표시 포함)
           ├─ 텍스트·CSV·HTML ─▶ 마크다운
           └─ 그 밖 ──────── failed(unsupported_type)
          ─▶ 가리기(나누기 전에: 두 줄에 걸친 "성명 / 홍길동" 도 가린다) ─▶ 블록(순번·쪽·시트)
DB 저장·업로드 경로·자동 분류는 정해지지 않아 여기서 하지 않는다(docs/requirements/ai_assistant-ingest.md 미정).
"""

import hashlib
import re
from collections import Counter
from pathlib import PurePath

from app.shared.config import settings
from app.shared.llm.transport import LLMUnavailable

from . import converters, figures, llm_ingest, masking
from .classify import Jev, classify
from .converters import BrokenFile, Ocr
from .detect import Unsupported, decode_text, detect
from .raw_store import LocalRawStore
from .schemas import Block, Content, PreprocessResult, Privacy, Quality, SourceInfo

MAX_BYTES = 25 * 1024 * 1024
MIN_PDF_CHARS = 20  # 이보다 글자가 적은 PDF 는 스캔본으로 본다
SCAN_UNREAD_PREFIX = "글자 없는 스캔 "  # 스캔 쪽을 읽을 수단이 없어 읽지 못했다는 노트의 시작(`_read_pdf`가 만들고 `_from_document`가 알아본다)


def _has_text(markdown: str) -> bool:
    """쪽 구분(\\f)과 공백을 빼고 실제 글자가 하나라도 있는가."""
    return bool(re.sub(r"\s+", "", markdown))


RAW_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "pdf": ".pdf",
    "docx": ".docx",
    "xlsx": ".xlsx",
    "pptx": ".pptx",
    "text": ".txt",
    "csv": ".csv",
    "html": ".html",
}


def ingest_file(
    group_id: str,
    data: bytes,
    filename: str = "",
    *,
    store: LocalRawStore | None = None,
    ocr: Ocr | None = None,
    jev: Jev | None = None,
    family=None,
) -> PreprocessResult:
    """원본을 원본 데이터 센터에 그대로 보관하고, 가린 결과와 (가린 글자로 한) 분류를 돌려준다.
    지원하지 않는 형식도 원본은 보관한다(나중에 지원되면 다시 처리할 수 있게).
    family(FamilyTagger)를 주면 가리기 전에 가족 이름을 `[가족:<user_id>]` 로 바꾼다(분류에도 실명이 나가지 않는다)."""
    result = preprocess(data, filename, ocr=ocr, family=family)
    if result.quality.error in ("empty_file", "too_large"):
        return result
    src = result.source
    ext = RAW_EXT.get(src.mime) or RAW_EXT.get(src.kind) or ".bin"
    store = store or LocalRawStore()
    ref = store.put(group_id, src.sha256, ext, data)
    # 분류는 반드시 가린 뒤에: classify 는 result.content(가린 글자)만 본다
    c = classify(result, jev=jev)
    update = {"raw_path": ref.path, "classification": c}
    # 사진: 원본은 그대로 두고 앱 화면용 사본(1080px WebP, 위치 정보 없음)을 원본 옆에 만든다
    if src.kind == "image" and result.quality.status != "failed":
        display = converters.make_display_copy(data)
        update["display_path"] = store.put_copy(
            group_id, src.sha256, "display", ".webp", display
        ).path
    return result.model_copy(update=update)


def preprocess(
    data: bytes, filename: str = "", *, ocr: Ocr | None = None, family=None
) -> PreprocessResult:
    """실패해도 예외를 내지 않고 quality.status = failed 로 돌려준다. content 는 가린 글자다."""
    name = PurePath(filename or "file").name[:200]
    source = SourceInfo(
        filename=name,
        kind="unsupported",
        mime="application/octet-stream",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    if not data:
        return _failed(source, "empty_file", "파일이 비어 있어요")
    if len(data) > MAX_BYTES:
        return _failed(source, "too_large", "파일이 너무 커요(25MB 이하)")
    try:
        source.kind, source.mime = detect(data, name)
    except Unsupported as e:
        return _failed(source, "unsupported_type", str(e))
    try:
        if source.kind == "image":
            return _from_image(source, data, ocr, family)
        return _from_document(source, data, ocr, family)
    except BrokenFile as e:
        return _failed(source, "broken_file", str(e))
    except LLMUnavailable:
        # Claude 로 읽거나 가리는 중이었다면 가리지 않은 글을 저장하지 않는다. 원본은 보관했으니 나중에 다시 처리할 수 있다
        return _failed(
            source,
            "llm_unavailable",
            "글을 읽는 서비스에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요",
        )


def _mask(text: str, family=None) -> tuple[str, Privacy]:
    if settings.ingest_llm_mask:
        # Claude 가 위치를 찾고(가족 이름 후보는 문맥으로 판단) 코드가 바꾼다. 호출이 실패하면 LLMUnavailable 이 올라가 파일이 failed 가 된다
        masked, counts, sensitive = llm_ingest.mask(text, family)
        notice = sensitive == "bankbook" and masking.is_account_notice(
            text
        )  # 가리기 전의 글로 판단
        return masked, Privacy(sensitive=sensitive, masked=counts, account_notice=notice)
    # 가족 이름은 가리기보다 먼저 자리표시로 바꾼다: 가린 뒤에는 `강**` 가 되어 누구인지 되돌릴 수 없다
    if family is not None:
        text = family.protect(text)
    # 처방전·신분증만 모두 가리고, 그 밖의 문서는 주민등록번호만 가린다
    kind = masking.sensitive_kind(text)
    notice = kind == "bankbook" and masking.is_account_notice(text)  # 가리기 전의 글로 판단
    counts: Counter = Counter()
    masked = masking.mask_text(text, kind, counts=counts)
    if family is not None:
        masked = family.expand(masked)
    return masked, Privacy(
        sensitive=kind, masked={k: v for k, v in counts.items() if v}, account_notice=notice
    )


def _from_image_llm(source: SourceInfo, data: bytes, family=None) -> PreprocessResult:
    """사진을 Claude 로 읽는다. 자신 없는 줄([?])은 확신도를 낮춰 기존 [불확실] 표시와 이어지게 한다."""
    image = converters.prepare_image(data)
    out = llm_ingest.ocr_image(image)
    if not out.text.strip():
        return PreprocessResult(
            source=source, quality=Quality(status="ok", warnings=["사진에 글자가 없어요"])
        )
    masked, privacy = _mask(
        out.text, family
    )  # 가리기가 줄 수를 바꿀 수 있어 가린 글에서 줄을 나눈다
    lines, confs = llm_ingest.line_confidence(masked)
    kept = [(t, c) for t, c in zip(lines, confs, strict=True) if t.strip()]
    blocks = [
        Block(index=i, type="ocr_line", text=t, confidence=c) for i, (t, c) in enumerate(kept)
    ]
    conf = round(sum(c for _, c in kept) / max(1, len(kept)), 3)
    doubtful = out.truncated or any(c < 0.75 for _, c in kept)
    warnings = ["글자가 흐려 일부만 읽혔을 수 있어요"] if doubtful else []
    return PreprocessResult(
        source=source,
        content=Content(text="\n".join(t for t, _ in kept), blocks=blocks),
        quality=Quality(
            status="partial" if warnings else "ok", text_confidence=conf, warnings=warnings
        ),
        privacy=privacy,
    )


def _from_image(source: SourceInfo, data: bytes, ocr: Ocr | None, family=None) -> PreprocessResult:
    """사진 속 글자는 Claude(`INGEST_LLM_OCR`)가 읽는다. 로컬 OCR 은 서비스에 없다(ADR 0025, `ocr` 는 시험이 끼우는 읽기 구성 요소일 뿐이다).
    읽을 수단이 하나도 없으면 실패다(가족 채팅 목적이면 외부 호출 전 동의 확인은 `consent_gate` 가 한다)."""
    if settings.ingest_llm_ocr:
        return _from_image_llm(source, data, family)
    if ocr is None:
        return _failed(
            source,
            "ocr_unavailable",
            "사진 속 글자를 읽을 수단이 없어요(서버에서 INGEST_LLM_OCR 를 켜야 해요)",
        )
    image = converters.prepare_image(data)
    lines = ocr.read(image)
    if not lines:
        return PreprocessResult(
            source=source, quality=Quality(status="ok", warnings=["사진에 글자가 없어요"])
        )
    # 줄을 이어 붙여 한 번에 가린 뒤 다시 줄로 나눈다(가리기는 줄 수를 바꾸지 않는다)
    text, privacy = _mask("\n".join(ln.text for ln in lines), family)
    masked_lines = text.split("\n")
    if len(masked_lines) != len(lines):  # 만일을 대비: 줄마다 따로 가린다
        masked_lines = [_mask(ln.text, family)[0] for ln in lines]
    blocks = [
        Block(index=i, type="ocr_line", text=t, confidence=round(ln.confidence, 3))
        for i, (t, ln) in enumerate(zip(masked_lines, lines, strict=True))
    ]
    conf = round(sum(ln.confidence for ln in lines) / len(lines), 3)
    warnings = ["글자가 흐려 일부만 읽혔을 수 있어요"] if conf < 0.75 else []
    return PreprocessResult(
        source=source,
        content=Content(text="\n".join(masked_lines), blocks=blocks),
        quality=Quality(
            status="partial" if warnings else "ok", text_confidence=conf, warnings=warnings
        ),
        privacy=privacy,
    )


def _from_document(
    source: SourceInfo, data: bytes, ocr: Ocr | None = None, family=None
) -> PreprocessResult:
    ocr_note = None
    if source.kind == "text":
        markdown = decode_text(data) or ""
    elif source.kind in ("csv", "html"):  # 한국 엑셀·메모장 CSV 는 CP949 라서 UTF-8 로 바꿔 넘긴다
        markdown = converters.to_markdown((decode_text(data) or "").encode("utf-8"), source.kind)
    elif source.kind == "pdf":
        # 쪽별 글자 층을 pdfium 으로 읽는다(한글 표 PDF 에서 MarkItDown 보다 읽는 순서가 정확하다)
        markdown, ocr_note = _read_pdf(data, ocr)
        if ocr_note and ocr_note.startswith(SCAN_UNREAD_PREFIX) and not _has_text(markdown):
            # 글자 층이 있는 쪽이 하나도 없고 스캔 쪽을 읽을 수단도 없다: 읽은 내용이 없는 "읽지 못한 부분" 자리표시를 정상 기록으로 만들지 않고,
            # 내용 없는 자리표시를 가리기·분류·챙길 일(외부 AI)로 보내지도 않는다. 사진(`_from_image`)과 같은 실패 코드를 쓴다.
            return _failed(
                source,
                "ocr_unavailable",
                "스캔 PDF 의 글자를 읽을 수단이 없어요(서버에서 INGEST_LLM_OCR 를 켜야 해요)",
            )
    else:
        markdown = converters.to_markdown(data, source.kind)
        if source.kind == "pptx":  # 변환기가 버린 그림 속 글자·내용을 Claude 로 설명해 넣는다
            markdown, ocr_note = figures.describe_pptx(data, markdown)
    markdown, privacy = _mask(markdown, family)
    blocks, pages = converters.markdown_blocks(markdown, source.kind)
    if source.kind in ("pptx", "xlsx"):  # 슬라이드·시트 번호와 블록 번호를 붙여 넘긴다
        text = converters.numbered_markdown(blocks, source.kind)
    else:
        text = "\n\n".join(b.text for b in blocks)
    if source.kind == "pdf" and len(text) < MIN_PDF_CHARS:
        status, warnings = "partial", ["스캔본 PDF 에서 글자를 거의 읽지 못했어요"]
    elif ocr_note:
        status, warnings = "partial", [ocr_note]
    elif not text:
        status, warnings = "partial", ["문서에 글자가 없어요"]
    else:
        status, warnings = "ok", []
    return PreprocessResult(
        source=source,
        content=Content(text=text, blocks=blocks, pages=pages),
        quality=Quality(status=status, warnings=warnings),
        privacy=privacy,
    )


def _read_pdf(data: bytes, ocr: Ocr | None) -> tuple[str, str | None]:
    """글자 층이 있는 쪽은 그대로 두고, 글자가 없는 쪽(스캔·사진)만 그림으로 바꿔 읽는다.
    (쪽을 \\f 로 이은 글, 확인이 필요한 이유). 스캔 쪽이 없으면 입력 글을 그대로 돌려준다.
    INGEST_LLM_OCR 가 켜져 있으면 글자 층이 있어도 표·머리말 구분이 더 정확한 Claude 로 쪽마다 읽는다(평가: 글자 층 꺼내기는 표를 한 줄로 이어 붙인다).
    로컬 OCR 은 서비스에 없다(ADR 0025): 꺼져 있고 시험이 끼운 읽기 구성 요소도 없으면 스캔 쪽은 읽지 못한 채 남는다."""
    if settings.ingest_llm_ocr:
        return llm_ingest.ocr_pdf(data)
    texts = converters.pdf_page_texts(data)
    scan = [
        i for i, t in enumerate(texts) if len(re.sub(r"\s+", "", t)) < converters.PDF_MIN_PAGE_CHARS
    ]
    pages = list(texts)
    if not scan:
        return "\f".join(pages), None
    if ocr is None:
        return "\f".join(
            pages
        ), f"{SCAN_UNREAD_PREFIX}{len(scan)}쪽은 읽는 수단이 없어서 읽지 못했어요"
    todo = scan[: converters.PDF_OCR_MAX_PAGES]
    reader = ocr
    for i, image in zip(todo, converters.pdf_page_images(data, todo), strict=True):
        pages[i] = "\n".join(ln.text for ln in reader.read(image))
    note = "스캔된 쪽은 OCR 로 읽었어요(틀린 글자가 있을 수 있어요)"
    if len(scan) > len(todo):
        note += f". 글자 없는 {len(scan)}쪽 중 앞 {len(todo)}쪽만 읽었어요"
    return "\f".join(pages), note


def _failed(source: SourceInfo, code: str, message: str) -> PreprocessResult:
    return PreprocessResult(
        source=source, quality=Quality(status="failed", error=code, warnings=[message])
    )
