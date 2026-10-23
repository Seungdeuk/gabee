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

from . import converters, masking
from .caption import Captioner
from .classify import Jev, Llm, classify
from .converters import BrokenFile, Ocr
from .detect import Unsupported, decode_text, detect
from .faces import Faces, default_faces
from .raw_store import LocalRawStore
from .schemas import Block, Content, People, PreprocessResult, Privacy, Quality, SourceInfo

MAX_BYTES = 25 * 1024 * 1024
MIN_PDF_CHARS = 20  # 이보다 글자가 적은 PDF 는 스캔본으로 본다
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
    llm: Llm | None = None,
    jev: Jev | None = None,
    faces: Faces | None = None,
    captioner: Captioner | None = None,
) -> PreprocessResult:
    """원본을 원본 데이터 센터에 그대로 보관하고, 가린 결과와 (가린 글자로 한) 분류를 돌려준다.
    지원하지 않는 형식도 원본은 보관한다(나중에 지원되면 다시 처리할 수 있게)."""
    result = preprocess(data, filename, ocr=ocr)
    if result.quality.error in ("empty_file", "too_large"):
        return result
    src = result.source
    ext = RAW_EXT.get(src.mime) or RAW_EXT.get(src.kind) or ".bin"
    store = store or LocalRawStore()
    ref = store.put(group_id, src.sha256, ext, data)
    # 분류는 반드시 가린 뒤에: classify 는 result.content(가린 글자)만 본다
    c = classify(result, llm, jev)
    update = {"raw_path": ref.path, "classification": c}
    # 사진: 원본은 그대로 두고 앱 화면용 사본(1080px WebP, 위치 정보 없음)을 원본 옆에 만든다
    if src.kind == "image" and result.quality.status != "failed":
        display = converters.make_display_copy(data)
        update["display_path"] = store.put_copy(
            group_id, src.sha256, "display", ".webp", display
        ).path
    # 글자 없는 사진은 이미지 모델이 설명을 붙인다(captioner 를 준 경우만 — 테스트는 모델을 부르지 않는다)
    if (
        captioner is not None
        and src.kind == "image"
        and result.quality.status != "failed"
        and not result.content.text.strip()
    ):
        caption = captioner.describe(data)
        if caption is not None:
            update["caption"] = caption
    # 가족 공유 사진만 찍힌 사람을 찾는다(문서 사진의 증명사진 등은 찾지 않음). 서버 안에서만 처리
    if src.kind == "image" and c is not None and c.route == "daily_share":
        finder = faces or default_faces()
        if finder is not None:
            update["people"] = People.model_validate(finder.identify(group_id, data))
    return result.model_copy(update=update)


def preprocess(data: bytes, filename: str = "", *, ocr: Ocr | None = None) -> PreprocessResult:
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
            return _from_image(source, data, ocr or converters.default_ocr())
        return _from_document(source, data, ocr)
    except BrokenFile as e:
        return _failed(source, "broken_file", str(e))


def _mask(text: str) -> tuple[str, Privacy]:
    # 처방전·신분증만 모두 가리고, 그 밖의 문서는 주민등록번호만 가린다
    kind = masking.sensitive_kind(text)
    counts: Counter = Counter()
    masked = masking.mask_text(text, kind, counts=counts)
    return masked, Privacy(sensitive=kind, masked={k: v for k, v in counts.items() if v})


def _from_image(source: SourceInfo, data: bytes, ocr: Ocr) -> PreprocessResult:
    image = converters.prepare_image(data)
    lines = ocr.read(image)
    if not lines:
        return PreprocessResult(
            source=source, quality=Quality(status="ok", warnings=["사진에 글자가 없어요"])
        )
    # 줄을 이어 붙여 한 번에 가린 뒤 다시 줄로 나눈다(가리기는 줄 수를 바꾸지 않는다)
    text, privacy = _mask("\n".join(ln.text for ln in lines))
    masked_lines = text.split("\n")
    if len(masked_lines) != len(lines):  # 만일을 대비: 줄마다 따로 가린다
        masked_lines = [_mask(ln.text)[0] for ln in lines]
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


def _from_document(source: SourceInfo, data: bytes, ocr: Ocr | None = None) -> PreprocessResult:
    if source.kind == "text":
        markdown = decode_text(data) or ""
    elif source.kind in ("csv", "html"):  # 한국 엑셀·메모장 CSV 는 CP949 라서 UTF-8 로 바꿔 넘긴다
        markdown = converters.to_markdown((decode_text(data) or "").encode("utf-8"), source.kind)
    else:
        markdown = converters.to_markdown(data, source.kind)
    ocr_note: str | None = None
    if source.kind == "pdf" and len(re.sub(r"\s+", "", markdown)) < MIN_PDF_CHARS:
        markdown, ocr_note = _ocr_scanned_pdf(data, ocr or converters.default_ocr())
    markdown, privacy = _mask(markdown)
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


def _ocr_scanned_pdf(data: bytes, ocr: Ocr) -> tuple[str, str | None]:
    """글자 층이 없는 PDF 의 쪽을 그림으로 바꿔 OCR 한다. (쪽을 \f 로 이은 글, 확인이 필요한 이유)."""
    images, total = converters.pdf_page_images(data)
    pages = ["\n".join(ln.text for ln in ocr.read(img)) for img in images]
    note = "스캔본 PDF 라서 OCR 로 읽었어요(틀린 글자가 있을 수 있어요)"
    if total > len(images):
        note += f". {total}쪽 중 앞 {len(images)}쪽만 읽었어요"
    return "".join(pages), note


def _failed(source: SourceInfo, code: str, message: str) -> PreprocessResult:
    return PreprocessResult(
        source=source, quality=Quality(status="failed", error=code, warnings=[message])
    )
