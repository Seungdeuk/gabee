"""사진을 외부 AI 에 보낼 때 쓰는 JPEG 만들기 도우미(놀이 기능 `play/photo_rec*` 가 쓴다).

예전에는 로컬 OCR 로 채팅 사진이 문서인지 가르는 `judge` 가 여기 있었지만, 로컬 OCR(RapidOCR)을 서비스에서 제거하면서(ADR 0025)
사진 판별은 로컬 SigLIP2 단독(`siglip_margin`, `library._judge_photo`)이 되었고 `judge` 는 지웠다.
"""

import io

from PIL import Image, ImageOps

READ_SIDE_PX = 1024  # 보낼 사진의 긴 변 상한


def _small_image(data: bytes) -> Image.Image:
    """긴 변 READ_SIDE_PX 이하로 줄인 RGB 사진. 큰 JPEG 는 줄여서 디코딩하고(draft), EXIF 회전을 반영한 뒤 메타데이터(EXIF·위치·주석)는 모두 버린다."""
    with Image.open(io.BytesIO(data)) as opened:
        opened.draft("RGB", (READ_SIDE_PX, READ_SIDE_PX))
        image = ImageOps.exif_transpose(opened).convert("RGB")
    image.thumbnail((READ_SIDE_PX, READ_SIDE_PX), Image.Resampling.LANCZOS)
    image.info = {}  # JPEG 주석(COM)·PNG 텍스트는 저장할 때 다시 쓰이므로 비운다
    return image


def to_judge_jpeg(data: bytes) -> bytes:
    """외부 AI 에 보낼 사진: EXIF 회전을 반영하고 긴 변 1024px 이하 JPEG 로 줄인다(위치·주석 같은 메타데이터는 옮기지 않는다)."""
    out = io.BytesIO()
    _small_image(data).save(out, "JPEG", quality=80)
    return out.getvalue()
