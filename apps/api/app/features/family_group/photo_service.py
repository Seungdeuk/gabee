"""프로필 사진(PR B) 업무 규칙.

- 받는 것: JPEG/PNG/WebP, 2MB 이하, 긴 변 8000px·총 1600만 화소 이하(압축 폭탄 방어). 실제 이미지인지 Pillow 로 열어 확인한다.
- 저장: EXIF 회전을 반영한 뒤 EXIF·메타데이터(GPS 등)를 모두 버리고, 가운데를 정사각형으로 잘라 최대 512x512 JPEG(quality 85)로 다시 만든다.
- 위치: settings.data_dir/profile_photos/<user_id>_<버전>.jpg. 파일 이름은 서버가 사용자 id·시각으로만 정한다(사용자 입력 무관).
  사용자 행을 잠가 업로드·삭제를 직렬화하고, 새 파일 → DB 커밋 성공 → 이전 파일 삭제 순서로 DB 를 기준으로 삼는다.
- 보기: 요청자와 대상이 같은 가족 그룹의 구성원일 때만(본인 포함). 아니면 사진이 있는지도 알려주지 않는다(404).
- 사진 내용·경로는 로그에 남기지 않고 외부 서비스로 보내지 않는다.
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

from app.shared.config import settings
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.rate_limit import FailureLimiter

from . import photo_repository as prepo
from .models import User
from .photo_schemas import ProfilePhotoOut

MAX_BYTES = 2 * 1024 * 1024
MAX_SIDE_PX = 8000  # 이보다 큰 그림은 픽셀을 읽기 전에 거절한다
MAX_PIXELS = 16_000_000  # 가로×세로 한도(디코딩 전 검사). 8000x8000 같은 그림이 메모리를 폭주시키지 못하게 한다
WORK_SIDE_PX = 1024  # 디코딩 직후 이 크기로 줄여서 작업한다
MAX_CONCURRENT = 2  # 동시에 처리하는 업로드 수
OUT_SIDE_PX = 512
JPEG_QUALITY = 85
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
UPLOAD_LIMIT = 5  # 사용자당 분당 업로드 시도 수
UPLOAD_WINDOW_SECONDS = 60
CACHE_CONTROL = "private, max-age=3600"
_SAFE_ID = re.compile(r"^[A-Za-z0-9]{1,32}$")

_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
# 한 프로세스 안의 동시 쓰기를 한 줄로(SQLite 등 행 잠금이 없는 DB 용). 여러 프로세스는 DB 행 잠금(FOR UPDATE)이 맡는다
_write_lock = threading.Lock()
upload_limiter = FailureLimiter()  # 프로세스 메모리(shared/rate_limit.py 의 한계 참고)


def _utc(value: datetime) -> datetime:
    """SQLite 는 시간대를 돌려주지 않으므로 UTC 로 본다."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def version_of(user: User) -> int | None:
    """사진을 바꾼 시각(밀리초). URL 의 ?v= 와 ETag 로 쓴다. 사진이 없으면 None."""
    if user.profile_photo_path is None or user.profile_photo_updated_at is None:
        return None
    return int(_utc(user.profile_photo_updated_at).timestamp() * 1000)


def photo_url(user: User) -> str | None:
    """응답에 넣는 상대 경로. 사진이 없으면 None."""
    version = version_of(user)
    return None if version is None else f"/family-group/users/{user.id}/photo?v={version}"


def photo_out(user: User) -> ProfilePhotoOut:
    return ProfilePhotoOut(
        photo_url=photo_url(user), photo_updated_at=user.profile_photo_updated_at
    )


def _photo_dir() -> Path:
    return Path(settings.data_dir) / "profile_photos"


def _photo_file(user_id: str) -> Path:
    """사용자 id 로만 만든 경로. id 는 서버가 만든 값이지만 한 번 더 확인한다."""
    if not _SAFE_ID.match(user_id):
        raise not_found("사진")
    return _photo_dir() / f"{user_id}.jpg"


def _invalid() -> ApiError:
    return bad_request("invalid_image", "JPEG, PNG, WebP 사진만 올릴 수 있어요")


def _flatten(image: Image.Image) -> Image.Image:
    """투명 부분을 흰색으로 채운 RGB 로."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return image.convert("RGB")


def normalize_image(data: bytes) -> bytes:
    """검증하고 정사각형 512px 이하 JPEG 바이트로 다시 만든다(메타데이터 없음).

    메모리 방어: 디코딩 전에 크기(긴 변·총 픽셀)를 거절하고, JPEG 는 draft 로 축소 디코딩하며, 그 외 형식은 읽자마자
    thumbnail 로 줄인 뒤에 회전·변환·크롭을 한다(큰 사본을 여러 장 만들지 않는다).
    """
    if len(data) > MAX_BYTES:
        raise ApiError(413, "photo_too_large", "사진은 2MB 이하만 올릴 수 있어요")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in ALLOWED_FORMATS:
                raise _invalid()
            width, height = probe.size
            if min(width, height) < 1:
                raise _invalid()
            if max(width, height) > MAX_SIDE_PX or width * height > MAX_PIXELS:
                raise bad_request("invalid_image", "사진이 너무 커요(1600만 화소 이하)")
            if probe.format == "JPEG":
                probe.draft(
                    "RGB", (WORK_SIDE_PX, WORK_SIDE_PX)
                )  # 디코딩 단계에서 1/2·1/4·1/8 로 줄인다
            probe.load()
            if probe.mode not in ("RGB", "RGBA", "L"):
                probe = probe.convert("RGBA" if "transparency" in probe.info else "RGB")
            probe.thumbnail((WORK_SIDE_PX, WORK_SIDE_PX), Image.Resampling.BILINEAR)
            image = ImageOps.exif_transpose(
                probe
            )  # 작아진 그림에서 회전 반영(이후 메타데이터는 버린다)
            image = _flatten(image)
    except ApiError:
        raise
    except Exception as exc:  # 깨진 파일·위장 파일·압축 폭탄 경고 등. 내용은 로그에 남기지 않는다
        raise _invalid() from exc
    side = min(image.size)
    left, top = (image.width - side) // 2, (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    if side > OUT_SIDE_PX:
        image = image.resize((OUT_SIDE_PX, OUT_SIDE_PX), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=JPEG_QUALITY)  # exif 를 넘기지 않으므로 메타데이터 없음
    return out.getvalue()


def _check_rate(user_id: str) -> None:
    key = f"photo:{user_id}"
    wait = upload_limiter.retry_after(key, UPLOAD_LIMIT, UPLOAD_WINDOW_SECONDS)
    if wait:
        raise ApiError(
            429,
            "too_many_uploads",
            "사진을 너무 자주 올렸어요. 잠시 후 다시 해 주세요",
            headers={"Retry-After": str(wait)},
        )
    upload_limiter.record(key)


def _version_file(user_id: str, version: int) -> Path:
    return _photo_dir() / f"{user_id}_{version}.jpg"


def _stored_file(user: User) -> Path | None:
    """DB 에 적힌 상대 경로를 검증해 실제 파일 경로로. 서버가 만든 형태(profile_photos/<id>[_<버전>].jpg)가 아니면 None."""
    path = user.profile_photo_path
    if path is None or not _SAFE_ID.match(user.id):
        return None
    if not re.fullmatch(rf"profile_photos/{re.escape(user.id)}(_\d+)?\.jpg", path):
        return None
    return _photo_dir() / path.split("/", 1)[1]


def upload_my_photo(db: Session, user: User, data: bytes) -> ProfilePhotoOut:
    """내 프로필 사진을 올리거나 바꾼다.

    사용자 행을 잠가 업로드·삭제를 직렬화하고, DB 를 기준으로 삼는다: 버전별 새 파일을 쓰고 → DB 커밋이 성공한 뒤에만 이전
    파일을 지운다(커밋이 실패하면 새 파일을 지운다).
    """
    _check_rate(user.id)
    if not _slots.acquire(blocking=False):  # 대기하지 않고 바로 거절(메모리 보호)
        raise ApiError(
            503, "photo_busy", "지금 사진을 처리하는 요청이 많아요. 잠시 후 다시 해 주세요"
        )
    try:
        jpeg = normalize_image(data)
    finally:
        _slots.release()
    _photo_file(user.id)  # id 형식 확인
    with _write_lock:
        return _store(db, user.id, jpeg)


def _store(db: Session, user_id: str, jpeg: bytes) -> ProfilePhotoOut:
    locked = prepo.lock_user(db, user_id)
    if locked is None:
        raise not_found("사용자")
    old = _stored_file(locked)
    now = datetime.now(UTC)
    now = now.replace(microsecond=now.microsecond // 1000 * 1000)  # 밀리초 단위(버전과 같은 값)
    target = _version_file(user_id, int(now.timestamp() * 1000))
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".{user_id}.{uuid.uuid4().hex}.tmp"
    try:
        tmp.write_bytes(jpeg)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    try:
        prepo.set_photo(db, locked, f"profile_photos/{target.name}", now)
        db.commit()
    except Exception:
        db.rollback()
        if old != target:
            target.unlink(missing_ok=True)
        raise
    if old is not None and old != target:
        old.unlink(missing_ok=True)
    db.refresh(locked)
    return photo_out(locked)


def delete_my_photo(db: Session, user: User) -> None:
    """내 사진을 지운다(없어도 성공). 커밋이 성공한 뒤에만 파일을 지운다."""
    with _write_lock:
        locked = prepo.lock_user(db, user.id)
        if locked is None:
            return
        old = _stored_file(locked)
        prepo.set_photo(db, locked, None, None)
        db.commit()
        if old is not None:
            old.unlink(missing_ok=True)
        _photo_file(locked.id).unlink(missing_ok=True)  # 예전 형식(<id>.jpg) 파일 정리


def photo_for_viewer(db: Session, viewer: User, target_id: str) -> tuple[bytes, User]:
    """대상 사진 바이트와 대상 사용자. 같은 가족이 아니거나 사진이 없으면 404."""
    target = prepo.get_user(db, target_id)
    if target is None or (
        target.id != viewer.id and not prepo.share_group(db, viewer.id, target.id)
    ):
        raise not_found("사진")
    if version_of(target) is None:
        raise not_found("사진")
    path = _stored_file(target)
    if path is None:
        raise not_found("사진")
    try:
        return path.read_bytes(), target
    except FileNotFoundError:
        raise not_found("사진") from None
