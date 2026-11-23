"""사진 한 장의 화질·중복 판단용 값(PR5): 선명도·노출·내용 해시·dHash. 서버 안에서만 계산하고 외부로 보내지 않는다. 결과는 숫자와 해시뿐이라 사진 내용을 복원할 수 없다.

값의 기준(선명도 τ·노출 가중)은 정답이 아니라 초기값이며, 합성 이미지로 순서가 맞는지만 확인한다(`tests/test_grouping.py`). 열 수 없는 이미지는 None 을 돌려준다
(그룹화는 화질 값이 없으면 중립값 0.5 를 쓴다)."""

import hashlib
import io
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

STATS_SIDE = 256  # 계산용으로 줄이는 긴 변
SHARP_TAU = 150.0  # 라플라시안 분산 → 0~1 선명도 변환의 기준값(초기값)


@dataclass(frozen=True)
class ImageStats:
    content_hash: str  # 원본 바이트의 sha256(같은 파일이면 같다)
    dhash: int  # 64비트 차이 해시(조금 줄이거나 다시 압축해도 비슷하다)
    sharpness: float  # 0~1
    exposure: float  # 0~1, 1 에 가까울수록 적정 노출


def _gray(data: bytes) -> Image.Image | None:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            return ImageOps.exif_transpose(opened).convert("L")
    except Exception:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 남기지 않고 조용히 없음 처리
        return None


def dhash(gray: Image.Image) -> int:
    small = np.asarray(gray.resize((9, 8), Image.Resampling.LANCZOS), dtype=np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def sharpness(gray: Image.Image) -> float:
    """라플라시안 분산을 0~1 로 바꾼 값. 흐릴수록 0 에 가깝다."""
    work = gray.copy()
    work.thumbnail((STATS_SIDE, STATS_SIDE), Image.Resampling.LANCZOS)
    a = np.asarray(work, dtype=np.float32)
    if a.shape[0] < 3 or a.shape[1] < 3:
        return 0.0
    lap = -4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:]
    return float(1.0 - math.exp(-float(lap.var()) / SHARP_TAU))


def exposure(gray: Image.Image) -> float:
    """평균 밝기가 중간에 가깝고 완전히 어둡거나 하얗게 날아간 화소가 적을수록 1 에 가깝다."""
    work = gray.copy()
    work.thumbnail((STATS_SIDE, STATS_SIDE), Image.Resampling.LANCZOS)
    a = np.asarray(work, dtype=np.float32) / 255.0
    mean = float(a.mean())
    clipped = float(((a < 0.02) | (a > 0.98)).mean())
    return float(min(max(1.0 - (abs(mean - 0.5) * 1.2 + clipped * 1.5), 0.0), 1.0))


def image_stats(data: bytes) -> ImageStats | None:
    gray = _gray(data)
    if gray is None:
        return None
    return ImageStats(
        content_hash=hashlib.sha256(data).hexdigest(),
        dhash=dhash(gray),
        sharpness=sharpness(gray),
        exposure=exposure(gray),
    )
