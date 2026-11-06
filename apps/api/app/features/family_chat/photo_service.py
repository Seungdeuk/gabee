"""채팅 사진 전송 업무 규칙.

- 받는 것: JPEG/PNG/WebP, 8MB 이하, 긴 변 12000px·총 2500만 화소 이하(압축 폭탄 방어). 실제 이미지인지 Pillow 로 열어 확인한다.
- 저장: EXIF 회전을 반영한 뒤 EXIF·GPS·XMP·ICC·JPEG 주석·PNG 텍스트 등 메타데이터를 모두 버리고, 긴 변 1600px 이하 JPEG(원본 대신 보관)와 400px 이하 썸네일을 만든다.
- 위치: settings.data_dir/chat_photos/<첨부 id>.jpg, <첨부 id>_t.jpg. 파일 이름은 서버가 만든 id 로만 정한다(사용자 입력 무관).
  파일을 먼저 쓰고 → 메시지와 첨부를 한 번에 DB 에 저장하고 → 실패하면 파일을 지운다.
- 보기: 그 방에 들어갈 수 있는 사람만(가족 전체방은 가족 구성원, 1:1 방은 두 사람). 아니면 사진이 있는지도 알려주지 않는다(404).
- 사진 내용·파일 경로는 로그에 남기지 않고 외부 서비스(AI 포함)로 보내지 않는다.
"""

import io
import os
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.rate_limit import FailureLimiter

from . import repository as repo
from . import service
from .models import Message, MessageAttachment
from .schemas import MessageOut

MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE_PX = 12000  # 이보다 큰 그림은 픽셀을 읽기 전에 거절한다
MAX_PIXELS = 25_000_000  # 가로×세로 한도(디코딩 전 검사)
WORK_SIDE_PX = 2048  # 디코딩 직후 이 크기로 줄여서 작업한다
FULL_SIDE_PX = 1600
THUMB_SIDE_PX = 400
FULL_QUALITY = 82
THUMB_QUALITY = 75
MAX_CONCURRENT = 2  # 동시에 처리하는 업로드 수
UPLOAD_LIMIT = 20  # 사용자당 분당 업로드 시도 수
UPLOAD_WINDOW_SECONDS = 60
CACHE_CONTROL = "private, max-age=31536000, immutable"  # 사진은 바뀌지 않는다(새 사진은 새 id)
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9]{1,32}$")

_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
upload_limiter = FailureLimiter()  # 프로세스 메모리(shared/rate_limit.py 의 한계 참고)


def _photo_dir() -> Path:
    return Path(settings.data_dir) / "chat_photos"


def _invalid() -> ApiError:
    return bad_request("invalid_image", "JPEG, PNG, WebP 사진만 보낼 수 있어요")


def _flatten(image: Image.Image) -> Image.Image:
    """투명 부분을 흰색으로 채운 RGB 로."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return image.convert("RGB")


def _jpeg(image: Image.Image, quality: int) -> bytes:
    image.info = {}  # JPEG 주석(COM)·PNG 텍스트 같은 원본 메타데이터가 저장 때 되살아나지 않게 비운다
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality)  # exif 도 넘기지 않으므로 메타데이터 없음
    return out.getvalue()


def process_image(data: bytes) -> tuple[bytes, bytes, int, int]:
    """검증하고 (원본 대신 보관할 JPEG, 썸네일 JPEG, 너비, 높이)로 다시 만든다(메타데이터 없음).

    메모리 방어: 디코딩 전에 크기(긴 변·총 픽셀)를 거절하고, JPEG 는 draft 로 축소 디코딩하며, 그 외 형식은 읽자마자
    thumbnail 로 줄인 뒤에 회전·변환을 한다(큰 사본을 여러 장 만들지 않는다).
    """
    if len(data) > MAX_BYTES:
        raise ApiError(413, "photo_too_large", "사진은 8MB 이하만 보낼 수 있어요")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise _invalid()
            width, height = probe.size
            if min(width, height) < 1:
                raise _invalid()
            if max(width, height) > MAX_SIDE_PX or width * height > MAX_PIXELS:
                raise bad_request("invalid_image", "사진이 너무 커요(2500만 화소 이하)")
            if probe.format == "JPEG":
                probe.draft("RGB", (WORK_SIDE_PX, WORK_SIDE_PX))
            probe.load()
            if probe.mode not in ("RGB", "RGBA", "L"):
                probe = probe.convert("RGBA" if "transparency" in probe.info else "RGB")
            probe.thumbnail((FULL_SIDE_PX, FULL_SIDE_PX), Image.Resampling.LANCZOS)
            image = ImageOps.exif_transpose(
                probe
            )  # 작아진 그림에서 회전 반영(이후 메타데이터는 버린다)
            image = _flatten(image)
    except ApiError:
        raise
    except Exception as exc:  # 깨진 파일·위장 파일·압축 폭탄 경고 등. 내용은 로그에 남기지 않는다
        raise _invalid() from exc
    full = _jpeg(image, FULL_QUALITY)
    thumb_image = image.copy()
    thumb_image.thumbnail((THUMB_SIDE_PX, THUMB_SIDE_PX), Image.Resampling.LANCZOS)
    return full, _jpeg(thumb_image, THUMB_QUALITY), image.width, image.height


def _check_rate(user_id: str) -> None:
    key = f"chatphoto:{user_id}"
    wait = upload_limiter.retry_after(key, UPLOAD_LIMIT, UPLOAD_WINDOW_SECONDS)
    if wait:
        raise ApiError(
            429,
            "too_many_uploads",
            "사진을 너무 자주 보냈어요. 잠시 후 다시 해 주세요",
            headers={"Retry-After": str(wait)},
        )
    upload_limiter.record(key)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{uuid.uuid4().hex}.tmp"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def attachment_files(attachment: MessageAttachment) -> tuple[Path, Path] | None:
    """DB 에 적힌 상대 경로가 서버가 만든 형태(chat_photos/<id>.jpg, <id>_t.jpg)일 때만 실제 경로로. 아니면 None."""
    if not _SAFE_ID.match(attachment.id):
        return None
    if attachment.path != f"chat_photos/{attachment.id}.jpg":
        return None
    if attachment.thumb_path != f"chat_photos/{attachment.id}_t.jpg":
        return None
    base = _photo_dir()
    return base / f"{attachment.id}.jpg", base / f"{attachment.id}_t.jpg"


def send_photo(
    db: Session,
    user: User,
    group_id: str,
    data: bytes,
    room_id: str | None = None,
    batch_id: str | None = None,
) -> MessageOut:
    """사진 메시지를 보낸다. 방에 들어갈 수 없으면 404(존재 여부를 숨김). batch_id 는 같은 번호끼리 한 묶음으로 보이게 저장한다."""
    room = service.resolve_room(db, user, group_id, room_id)
    _check_rate(user.id)
    if not _slots.acquire(blocking=False):  # 대기하지 않고 바로 거절(메모리 보호)
        raise ApiError(
            503, "photo_busy", "지금 사진을 처리하는 요청이 많아요. 잠시 후 다시 해 주세요"
        )
    try:
        full, thumb, width, height = process_image(data)
    finally:
        _slots.release()
    attachment = MessageAttachment(
        group_id=group_id,
        room_id=room.id,
        width=width,
        height=height,
        batch_id=batch_id,
        size_bytes=len(full),
        path="",
        thumb_path="",
    )
    attachment.id = uuid.uuid4().hex[:12]
    attachment.path = f"chat_photos/{attachment.id}.jpg"
    attachment.thumb_path = f"chat_photos/{attachment.id}_t.jpg"
    files = attachment_files(attachment)
    if files is None:  # 방금 서버가 만든 id 라 일어나지 않지만, 이상하면 저장하지 않는다
        raise ApiError(500, "photo_failed", "사진을 저장하지 못했어요. 다시 시도해 주세요")
    written: list[Path] = []
    try:
        _write(files[0], full)
        written.append(files[0])
        _write(files[1], thumb)
        written.append(files[1])
        message = Message(
            group_id=group_id,
            room_id=room.id,
            user_id=user.id,
            text="",
            created_at=datetime.now(UTC),
        )
        message, attachment = repo.add_photo_message(db, message, attachment)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    try:
        repo.advance_read(db, room.id, user.id, message.id)  # 내가 보낸 메시지는 읽은 것으로
    except Exception:
        db.rollback()  # 사진은 이미 저장됐다. 읽음 위치 실패로 500 을 주면 재시도로 같은 사진이 두 번 간다
    return service.message_out(message, user.name, attachment)


def photo_for_viewer(
    db: Session, user: User, group_id: str, attachment_id: str, thumb: bool
) -> tuple[bytes, str]:
    """사진 바이트와 ETag. 방에 들어갈 수 없거나 없는 사진이면 모두 같은 404."""
    attachment = repo.get_attachment(db, attachment_id) if _SAFE_ID.match(attachment_id) else None
    if attachment is None or attachment.group_id != group_id:
        raise not_found("사진")
    service.resolve_room(db, user, group_id, attachment.room_id)  # 못 들어가는 방이면 404
    files = attachment_files(attachment)
    if files is None:
        raise not_found("사진")
    try:
        return files[1 if thumb else 0].read_bytes(), f'"{attachment.id}{"t" if thumb else ""}"'
    except FileNotFoundError:
        raise not_found("사진") from None
