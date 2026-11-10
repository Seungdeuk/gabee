"""가족 놀이터 그림·사진 파일. 서버 디스크(`settings.data_dir`) 아래 `play/` 에 두고 DB 에는 상대 경로만 적는다.

- 그림(이게 뭐게): PNG 만, 2MB 이하. 서버가 다시 만들어 저장한다(`play/drawings/<가족id>/<놀이id>.png`).
- 사진(찰칵! 탐정단): JPEG/PNG/WebP, 8MB 이하. EXIF 회전을 반영한 뒤 EXIF·GPS 를 모두 버리고 긴 변 1600px 이하
  JPEG 로 다시 만든다(`play/photos/<가족id>/<놀이id>.jpg`).
- 파일 이름은 서버가 만든 id 로만 짓고 사용자 입력은 경로에 쓰지 않는다. 읽을 때도 DB 경로가 서버가 만든 형태인지 확인한다.
- 문제로 푸는 사람에게는 사진 원본이 아니라 확대해서 잘라낸 부분만 보낸다(정답 공개 전에 원본이 새지 않게).
"""

import io
import os
import re
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from app.shared.config import settings
from app.shared.errors import ApiError, bad_request, not_found

DRAW_MAX_BYTES = 2 * 1024 * 1024
PHOTO_MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE_PX = 8000  # 이보다 큰 그림은 픽셀을 읽기 전에 거절(압축 폭탄 방어)
MAX_PIXELS = 24_000_000
DRAW_SIDE_PX = 1600
PHOTO_SIDE_PX = 1600
CROP_OUT_PX = 900  # 잘라낸 부분을 보낼 때의 긴 변
JPEG_QUALITY = 85

_DRAW_PATH = re.compile(r"^play/drawings/[A-Za-z0-9]{1,32}/[A-Za-z0-9]{1,32}\.png$")
_PHOTO_PATH = re.compile(r"^play/photos/[A-Za-z0-9]{1,32}/[A-Za-z0-9]{1,32}\.jpg$")


def _open(data: bytes, allowed: set[str], max_bytes: int) -> Image.Image:
    if not data:
        raise bad_request("invalid_image", "이미지 파일을 올려 주세요")
    if len(data) > max_bytes:
        raise ApiError(
            413, "image_too_large", f"이미지는 {max_bytes // (1024 * 1024)}MB 이하여야 해요"
        )
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in allowed:
            raise bad_request("invalid_image", "지원하지 않는 이미지 형식이에요")
        w, h = img.size
        if w < 1 or h < 1 or max(w, h) > MAX_SIDE_PX or w * h > MAX_PIXELS:
            raise bad_request("invalid_image", "이미지가 너무 커요")
        img.load()
        return img
    except ApiError:
        raise
    except Exception as exc:  # 깨진 파일·위장 파일
        raise bad_request("invalid_image", "이미지를 읽을 수 없어요") from exc


def _fit(img: Image.Image, side: int) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if max(img.size) > side:
        img.thumbnail((side, side), Image.LANCZOS)
    return img


def make_draw_png(data: bytes) -> bytes:
    img = _fit(_open(data, {"PNG"}, DRAW_MAX_BYTES), DRAW_SIDE_PX)
    out = io.BytesIO()
    img.convert("RGBA").save(out, format="PNG", optimize=True)  # 메타데이터는 버린다
    return out.getvalue()


def make_photo_jpeg(data: bytes) -> bytes:
    img = _fit(_open(data, {"JPEG", "PNG", "WEBP"}, PHOTO_MAX_BYTES), PHOTO_SIDE_PX)
    out = io.BytesIO()
    img.convert("RGB").save(
        out, format="JPEG", quality=JPEG_QUALITY, optimize=True
    )  # EXIF·GPS 는 버린다
    return out.getvalue()


def _root() -> Path:
    return Path(settings.data_dir)


def draw_path(group_id: str, item_id: str) -> str:
    return f"play/drawings/{group_id}/{item_id}.png"


def photo_path(group_id: str, item_id: str) -> str:
    return f"play/photos/{group_id}/{item_id}.jpg"


def write(rel_path: str, data: bytes) -> None:
    """임시 파일에 쓴 뒤 바꿔치기해서 반쪽 파일이 남지 않게 한다."""
    if not (_DRAW_PATH.match(rel_path) or _PHOTO_PATH.match(rel_path)):
        raise ValueError("놀이터 파일 경로가 올바르지 않아요")
    target = _root() / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def delete(rel_path: str) -> None:
    if _DRAW_PATH.match(rel_path) or _PHOTO_PATH.match(rel_path):
        (_root() / rel_path).unlink(missing_ok=True)


def read(rel_path: str) -> bytes:
    if not (_DRAW_PATH.match(rel_path) or _PHOTO_PATH.match(rel_path)):
        raise not_found("이미지")
    path = _root() / rel_path
    try:
        return path.read_bytes()
    except OSError as exc:
        raise not_found("이미지") from exc


def effective_zoom(zoom: int, shrinks: int) -> int:
    """ "조금 줄여 보기"를 한 번 쓸 때마다 확대 배율이 절반이 된다(최소 1배 = 사진 전체)."""
    return max(1, zoom // (2 ** max(0, shrinks)))


def crop_zoom(jpeg: bytes, box_x: float, box_y: float, zoom: int, shrinks: int) -> bytes:
    """(box_x, box_y)(0~1, 확대 창의 가운데)를 중심으로 1/배율 크기를 잘라 보낸다."""
    img = Image.open(io.BytesIO(jpeg))
    z = effective_zoom(zoom, shrinks)
    w, h = img.size
    cw, ch = max(1, round(w / z)), max(1, round(h / z))
    left = min(max(0, round(box_x * w - cw / 2)), w - cw)
    top = min(max(0, round(box_y * h - ch / 2)), h - ch)
    part = img.crop((left, top, left + cw, top + ch))
    if max(part.size) > CROP_OUT_PX:
        part.thumbnail((CROP_OUT_PX, CROP_OUT_PX), Image.LANCZOS)
    out = io.BytesIO()
    part.convert("RGB").save(out, format="JPEG", quality=JPEG_QUALITY)
    return out.getvalue()
