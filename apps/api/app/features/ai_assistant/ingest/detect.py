"""파일 형식 판별. 확장자는 바꿔 올릴 수 있으므로 파일 앞부분(매직 바이트)과 내용으로 판단한다."""

import io
import zipfile
from pathlib import PurePath

from .schemas import FileKind

HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"}
TEXT_EXTS = {".txt": "text", ".md": "text", ".csv": "csv", ".html": "html", ".htm": "html"}
MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text": "text/plain",
    "csv": "text/csv",
    "html": "text/html",
}


class Unsupported(Exception):
    """지원하지 않는 형식. message 는 사용자에게 보여 줄 한국어 문장."""


def detect(data: bytes, filename: str = "") -> tuple[FileKind, str]:
    """(종류, MIME). 모르는 형식이면 Unsupported."""
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in HEIF_BRANDS:
        return "image", "image/heic"
    if head.startswith(b"%PDF-"):
        return "pdf", MIME["pdf"]
    if head.startswith(b"PK\x03\x04"):
        return _zip_kind(data)
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise Unsupported("예전 형식(hwp·doc·xls·ppt)은 아직 지원하지 않아요")
    return _text_kind(data, filename)


def _zip_kind(data: bytes) -> tuple[FileKind, str]:
    try:
        names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    except zipfile.BadZipFile:
        raise Unsupported("압축 파일이 깨져 있어요") from None
    for kind, marker in (
        ("docx", "word/document.xml"),
        ("xlsx", "xl/workbook.xml"),
        ("pptx", "ppt/presentation.xml"),
    ):
        if marker in names:
            return kind, MIME[kind]
    if any(n.startswith("Contents/section") for n in names):
        raise Unsupported("한글(hwpx) 파일은 아직 지원하지 않아요")
    raise Unsupported("지원하지 않는 압축 파일이에요")


def _text_kind(data: bytes, filename: str) -> tuple[FileKind, str]:
    if b"\x00" in data[:4096] or decode_text(data) is None:
        raise Unsupported("지원하지 않는 형식이에요")
    kind = TEXT_EXTS.get(PurePath(filename).suffix.lower())
    if kind is None:
        start = data[:200].lstrip().lower()
        kind = "html" if start.startswith((b"<!doctype html", b"<html")) else "text"
    return kind, MIME[kind]


def decode_text(data: bytes) -> str | None:
    """UTF-8(BOM 포함) → CP949(한국 엑셀·메모장 CSV) 순으로 시도한다."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None
