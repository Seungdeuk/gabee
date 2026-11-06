"""채팅 문서 파일 전송 업무 규칙.

- 받는 것: 문서류만(pdf, doc/docx, xls/xlsx, ppt/pptx, hwp/hwpx, txt, csv), 20MB 이하. 이미지는 사진 경로(/photos)를 쓰고,
  실행 파일·압축 파일(zip 등)·HTML·SVG·스크립트는 받지 않는다. 확장자 허용 목록 + 파일 앞부분 시그니처가 맞아야 한다.
- 위치: settings.data_dir/chat_files/<첨부 id><허용 확장자>. 파일 이름은 서버가 만든 id 로만 정한다(사용자 파일명은 DB filename 에만,
  경로 성분·제어 문자를 정리하고 길이를 제한한 표시용 값).
- 내려받기: 사진과 같은 권한(방에 들어갈 수 있는 사람만, 아니면 모두 404). Content-Disposition: attachment + nosniff,
  미디어 타입은 허용 목록의 값이라 브라우저가 열어서 실행하지 않는다.
- 문서 내용·파일명은 로그에 남기지 않고 AI·검색·외부 서비스로 보내지 않는다(메시지 text 는 빈 문자열이다).
"""

import io
import re
import threading
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared import chat_library
from app.shared.config import settings
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.rate_limit import FailureLimiter

from . import chat_push, photo_service, service
from . import repository as repo
from .models import FAMILY, Message, MessageAttachment
from .schemas import MessageOut

MAX_BYTES = 20 * 1024 * 1024
MAX_FILENAME_CHARS = 120
MAX_CONCURRENT = 2  # 동시에 처리하는 업로드 수
UPLOAD_LIMIT = 20  # 사용자당 분당 업로드 시도 수
UPLOAD_WINDOW_SECONDS = 60
READ_CHUNK = 1024 * 1024
CACHE_CONTROL = "private, no-store"
FALLBACK_TYPE = "application/octet-stream"

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP = b"PK\x03\x04"
_SAFE_ID = re.compile(r"^[A-Za-z0-9]{1,32}$")
_BAD_NAME_CHARS = re.compile(r'[<>:"|?*\\/]')
_TEXT_REJECT_PREFIXES = (b"<!doctype", b"<html", b"<svg", b"<?xml", b"<script", b"#!")


@dataclass(frozen=True)
class FileKind:
    content_type: str
    check: str  # pdf | ole | ooxml:<폴더> | hwpx | text


ALLOWED: dict[str, FileKind] = {
    ".pdf": FileKind("application/pdf", "pdf"),
    ".doc": FileKind("application/msword", "ole"),
    ".docx": FileKind(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "ooxml:word/document.xml",
    ),
    ".xls": FileKind("application/vnd.ms-excel", "ole"),
    ".xlsx": FileKind(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "ooxml:xl/workbook.xml"
    ),
    ".ppt": FileKind("application/vnd.ms-powerpoint", "ole"),
    ".pptx": FileKind(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "ooxml:ppt/presentation.xml",
    ),
    ".hwp": FileKind("application/x-hwp", "ole"),
    ".hwpx": FileKind("application/vnd.hancom.hwpx", "hwpx"),
    ".txt": FileKind("text/plain", "text"),
    ".csv": FileKind("text/csv", "text"),
}

_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
upload_limiter = FailureLimiter()  # 프로세스 메모리(사진과 따로 센다)


def _file_dir() -> Path:
    return Path(settings.data_dir) / "chat_files"


def _invalid(message: str = "허용되지 않는 파일이에요. 문서 파일만 보낼 수 있어요") -> ApiError:
    return bad_request("invalid_file", message)


def clean_filename(raw: str | None) -> tuple[str, str]:
    """사용자 파일명을 표시용으로 정리한다: (정리한 이름, 소문자 확장자). 경로는 마지막 성분만, 제어·서식 문자 제거, 길이 제한.
    확장자가 허용 목록에 없으면 400."""
    name = unicodedata.normalize("NFC", (raw or "").replace("\x00", ""))  # 맥의 자모 분리를 합친다
    name = re.split(r"[\\/]", name)[-1]
    name = "".join(
        ch for ch in name if unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co", "Zl", "Zp")
    )
    name = _BAD_NAME_CHARS.sub("", name).strip().strip(".").strip()
    dot = name.rfind(".")
    ext = name[dot:].lower() if dot > 0 else ""
    if ext not in ALLOWED:
        raise _invalid()
    stem = name[:dot].strip().strip(".").strip() or "파일"
    stem = stem[: MAX_FILENAME_CHARS - len(ext)]
    return stem + ext, ext


def _looks_like_text(data: bytes) -> bool:
    if b"\x00" in data or data.startswith(b"MZ"):
        return False
    head = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith(_TEXT_REJECT_PREFIXES):
        return False
    for encoding in ("utf-8", "cp949"):  # UTF-16 은 NUL 바이트가 있어 위에서 걸러진다
        try:
            data.decode(encoding)
            return True
        except UnicodeDecodeError:
            continue
    return False


def _hwpx_ok(archive: zipfile.ZipFile) -> bool:
    """hwpx 는 mimetype 항목이 application/hwp+zip 이다(100바이트 이하 항목 하나만 읽는다). mimetype 이 없으면 Contents/header.xml 로 본다."""
    try:
        info = archive.getinfo("mimetype")
    except KeyError:
        return "Contents/header.xml" in archive.namelist()
    if info.file_size > 100:
        return False
    return archive.read(info).decode("ascii", "ignore").strip().startswith("application/hwp")


def _zip_ok(data: bytes, check: str) -> bool:
    """zip 계열 확인. 항목 목록만 읽고 압축을 풀지 않는다(zip 폭탄 방지, hwpx 의 작은 mimetype 항목만 예외)."""
    if data[:4] != _ZIP:
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if check == "hwpx":
                return _hwpx_ok(archive)
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError):
        return False
    return "[Content_Types].xml" in names and check[6:] in names  # ooxml:<필수 항목>


def validate_content(ext: str, data: bytes) -> None:
    """확장자와 파일 앞부분(시그니처)이 맞는지 확인한다. 맞지 않으면 400. 내용은 로그에 남기지 않는다."""
    if not data:
        raise _invalid("빈 파일은 보낼 수 없어요")
    check = ALLOWED[ext].check
    if check == "pdf":
        ok = data[:5] == b"%PDF-"
    elif check == "ole":
        ok = data[:8] == _OLE
    elif check == "text":
        ok = _looks_like_text(data)
    else:
        ok = _zip_ok(data, check)
    if not ok:
        raise _invalid("파일 내용이 확장자와 맞지 않아요")


def read_limited(source: BinaryIO) -> bytes:
    """한도보다 1바이트만 더 읽어 초과를 안다. 조각으로 읽으므로 한도를 넘는 큰 파일을 통째로 올리지 않는다."""
    buffer = bytearray()
    while True:
        chunk = source.read(READ_CHUNK)
        if not chunk:
            return bytes(buffer)
        buffer += chunk
        if len(buffer) > MAX_BYTES:
            raise ApiError(413, "file_too_large", "파일은 20MB 이하만 보낼 수 있어요")


def _check_rate(user_id: str) -> None:
    key = f"chatfile:{user_id}"
    wait = upload_limiter.retry_after(key, UPLOAD_LIMIT, UPLOAD_WINDOW_SECONDS)
    if wait:
        raise ApiError(
            429,
            "too_many_uploads",
            "파일을 너무 자주 보냈어요. 잠시 후 다시 해 주세요",
            headers={"Retry-After": str(wait)},
        )
    upload_limiter.record(key)


def attachment_path(attachment: MessageAttachment) -> Path | None:
    """문서 첨부의 실제 경로. DB 의 상대 경로가 서버가 만든 형태(chat_files/<id><허용 확장자>)일 때만, 아니면 None."""
    if attachment.kind != "file" or not _SAFE_ID.match(attachment.id):
        return None
    for ext in ALLOWED:
        if attachment.path == f"chat_files/{attachment.id}{ext}":
            return _file_dir() / f"{attachment.id}{ext}"
    return None


def attachment_paths(attachment: MessageAttachment) -> tuple[Path, ...]:
    """삭제할 디스크 파일들(사진은 원본·썸네일, 문서는 파일 하나). 서버가 만든 형태가 아니면 빈 값."""
    if attachment.kind == "file":
        path = attachment_path(attachment)
        return (path,) if path else ()
    return photo_service.attachment_files(attachment) or ()


def _attachment_exists(db: Session, group_id: str, attachment_id: str) -> bool:
    """이 가족의 채팅 첨부가 아직 있는지(메시지를 지우면 첨부 행도 지워진다). 문서함 자동 등록이 처리 도중 지워졌는지 확인하는 데 쓴다."""
    found = repo.get_attachment(db, attachment_id)
    return found is not None and found.group_id == group_id


chat_library.register_exists(_attachment_exists)


def send_file(
    db: Session,
    user: User,
    group_id: str,
    source: BinaryIO,
    filename: str | None,
    room_id: str | None = None,
) -> MessageOut:
    """문서 메시지를 보낸다. 방에 들어갈 수 없으면 404(존재 여부를 숨김)."""
    room = service.resolve_room(db, user, group_id, room_id)
    clean, ext = clean_filename(filename)
    _check_rate(user.id)
    if not _slots.acquire(blocking=False):  # 대기하지 않고 바로 거절(메모리 보호)
        raise ApiError(
            503, "file_busy", "지금 파일을 처리하는 요청이 많아요. 잠시 후 다시 해 주세요"
        )
    try:
        data = read_limited(source)
        validate_content(ext, data)
    finally:
        _slots.release()
    attachment = MessageAttachment(
        kind="file",
        group_id=group_id,
        room_id=room.id,
        size_bytes=len(data),
        filename=clean,
        content_type=ALLOWED[ext].content_type,
        path="",
    )
    attachment.id = uuid.uuid4().hex[:12]
    attachment.path = f"chat_files/{attachment.id}{ext}"
    target = attachment_path(attachment)
    if target is None:  # 방금 서버가 만든 id 라 일어나지 않지만, 이상하면 저장하지 않는다
        raise ApiError(500, "file_failed", "파일을 저장하지 못했어요. 다시 시도해 주세요")
    try:
        photo_service._write(target, data)
        message = Message(
            group_id=group_id,
            room_id=room.id,
            user_id=user.id,
            text="",
            created_at=datetime.now(UTC),
        )
        message, attachment = repo.add_photo_message(db, message, attachment)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    try:
        repo.advance_read(db, room.id, user.id, message.id)
    except Exception:
        db.rollback()  # 파일은 이미 저장됐다. 읽음 위치 실패로 500 을 주면 재시도로 같은 파일이 두 번 간다
    chat_push.notify_new_message(db, room, message)
    if (
        room.kind == FAMILY
    ):  # 가족 전체방의 문서만 가족 공유 문서함에 자동 등록한다(1:1 방은 제외, 실패해도 전송은 그대로)
        chat_library.document_posted(
            group_id, user.id, attachment.id, clean, ALLOWED[ext].content_type, data
        )
    return service.message_out(message, user.name, attachment)


def file_for_viewer(
    db: Session, user: User, group_id: str, attachment_id: str
) -> tuple[Path, MessageAttachment]:
    """문서 경로와 첨부 정보(내용은 라우터가 스트리밍한다). 방에 들어갈 수 없거나 없는 문서면 모두 같은 404."""
    attachment = repo.get_attachment(db, attachment_id) if _SAFE_ID.match(attachment_id) else None
    if attachment is None or attachment.group_id != group_id or attachment.kind != "file":
        raise not_found("파일")
    service.resolve_room(db, user, group_id, attachment.room_id)  # 못 들어가는 방이면 404
    path = attachment_path(attachment)
    if path is None:
        raise not_found("파일")
    if not path.is_file():
        raise not_found("파일")
    return path, attachment


def download_headers(attachment: MessageAttachment) -> dict[str, str]:
    """RFC 5987 로 한글 파일명을 퍼센트 인코딩해 내려받기로만 열리게 한다."""
    name = attachment.filename or "file"
    return {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": CACHE_CONTROL,
    }


def media_type(attachment: MessageAttachment) -> str:
    """허용 목록에 있는 값만 쓰고, 아니면 octet-stream."""
    known = {kind.content_type for kind in ALLOWED.values()}
    return attachment.content_type if attachment.content_type in known else FALLBACK_TYPE
