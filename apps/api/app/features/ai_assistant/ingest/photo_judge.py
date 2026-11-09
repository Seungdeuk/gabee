"""채팅 사진이 종이 문서를 찍은 것인지 일반 사진인지 가른다. 서버에 있는 로컬 OCR 만 쓰고 외부로 보내지 않는다.

사진을 작게 줄여 읽은 뒤, 확신도가 충분한 줄의 글자(한글·영문·숫자) 수와 줄 수로 판단한다.
- 문서: 글자가 많고 줄도 여러 개  → 자동으로 문서함에 읽어 넣는다
- 일반 사진: 읽힌 글자가 거의 없음 → 아무것도 하지 않는다
- 애매함: 그 사이(큰 글씨 포스터, 간판이 많은 거리 등) → 자동으로 하지 않고 사용자가 "문서로 저장"을 누르게 한다

기준 숫자는 실제 사진 15장(문서 8, 거리·음식 7)을 재서 정했다. 문서 사진은 좋은 글자 147~1050자·8줄 이상,
거리·음식 사진은 27자 이하였다. 틈(50~100자)은 일부러 넓게 둬서 헷갈리면 사용자에게 맡긴다.
"""

import io
import logging
import re
from dataclasses import dataclass

from PIL import Image, ImageOps

from .converters import Ocr

logger = logging.getLogger(__name__)

DOCUMENT = "document"
PHOTO = "photo"
UNSURE = "unsure"

READ_SIDE_PX = 1024  # 판별용으로 줄이는 긴 변(전체 읽기보다 훨씬 빠르다)
MIN_CONFIDENCE = 0.6  # 이보다 확신도가 낮은 줄은 글자로 세지 않는다(질감을 글자로 잘못 읽은 경우)
DOCUMENT_MIN_CHARS = 100
DOCUMENT_MIN_LINES = 6
PHOTO_MAX_CHARS = 50

_MEANINGFUL = re.compile(r"[0-9A-Za-z가-힣]")


@dataclass(frozen=True)
class Verdict:
    kind: str  # DOCUMENT | PHOTO | UNSURE
    chars: int
    lines: int


def to_judge_jpeg(data: bytes) -> bytes:
    """Claude 판별에 보낼 사진: EXIF 회전을 반영하고 긴 변 1024px 이하 JPEG 로 줄인다(위치 같은 메타데이터는 옮기지 않는다)."""
    with Image.open(io.BytesIO(data)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    image.thumbnail((READ_SIDE_PX, READ_SIDE_PX), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=80)
    return out.getvalue()


def judge(data: bytes, ocr: Ocr) -> Verdict:
    """사진 바이트를 문서/일반 사진/애매함으로 가른다. 열 수 없거나 읽기에 실패하면 애매함(자동으로 하지 않는다)."""
    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((READ_SIDE_PX, READ_SIDE_PX), Image.Resampling.LANCZOS)
        lines = [ln for ln in ocr.read(image) if ln.confidence >= MIN_CONFIDENCE]
    except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        logger.warning("photo judge failed error=%s", type(exc).__name__)
        return Verdict(UNSURE, 0, 0)
    chars = sum(len(_MEANINGFUL.findall(ln.text)) for ln in lines)
    if chars >= DOCUMENT_MIN_CHARS and len(lines) >= DOCUMENT_MIN_LINES:
        return Verdict(DOCUMENT, chars, len(lines))
    if chars < PHOTO_MAX_CHARS:
        return Verdict(PHOTO, chars, len(lines))
    return Verdict(UNSURE, chars, len(lines))
