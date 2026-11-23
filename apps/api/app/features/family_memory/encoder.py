"""이미지 인코더(PR4): 사진 한 장을 정규화된 임베딩 벡터로 바꾼다. **모델은 이 서버 안에서만 돌고 외부로 사진을 보내지 않는다**(ADR 0020).

- 이 모듈은 가볍다: 맨 위에서는 표준 라이브러리와 Pillow 만 쓴다. `torch`·`transformers` 는 `Siglip2Encoder.load()` 안에서만 가져오므로, 웹 프로세스가 이 모듈을
  불러와도 모델이 올라가거나 의존성이 필요해지지 않는다(모델은 별도 워커 프로세스에서만 로드한다).
- `FakeEncoder`: 모델 파일이 없는 환경(시험·개발)용 결정적 가짜. 같은 입력이면 같은 벡터, 열 수 없는 이미지는 오류.
- `Siglip2Encoder`: SigLIP2(PoC 와 같은 `google/siglip2-base-patch16-224`, 이미지 특징 768차원). 이미 내려받은 로컬 파일만 쓰고(`local_files_only`, HF 오프라인)
  **다운로드하지 않는다.** GPU 메모리가 모자라면(OOM) 캐시를 비우고 `EncoderResourceError` 로 알려 작업 실패 규칙(재시도·상한)에 맡긴다.
- 로그에는 시간(ms)·메모리(MB)·예외 종류 이름만 남기고 사진 내용·경로·라벨을 남기지 않는다."""

import io
import logging
import math
import struct
import time
from typing import Protocol

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

MAX_PIXELS = 25_000_000  # 디코딩 전 크기 검사(압축 폭탄 방어). 채팅 사진 저장본은 긴 변 1600px 이하라 정상 입력은 훨씬 작다
NORM_TOLERANCE = 1e-3


class EncoderError(Exception):
    """추론을 못 했다(열 수 없는 이미지·모델 오류). 작업은 재시도 규칙(상한·backoff)에 따라 다시 시도되거나 실패로 끝난다."""


class EncoderUnavailable(EncoderError):
    """인코더를 만들거나 로드하지 못했다(설정 꺼짐·모델 파일 없음·라이브러리 없음)."""


class EncoderResourceError(EncoderError):
    """GPU 메모리 부족 등 자원 오류. 캐시를 비운 뒤 알린다."""


# ---------- 전처리·검증 ----------
def preprocess(data: bytes) -> Image.Image:
    """사진 바이트를 RGB 이미지로 연다: EXIF 회전을 반영하고 메타데이터(EXIF·위치·주석)는 버린다. 열 수 없거나 너무 크면 EncoderError."""
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if opened.width * opened.height > MAX_PIXELS:
                raise EncoderError("ImageTooLarge")
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except EncoderError:
        raise
    except Exception:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 남긴다
        raise EncoderError("InvalidImage") from None
    image.info = {}
    return image


def normalize(vector: list[float]) -> list[float]:
    """L2 정규화. 값이 유한하지 않거나 크기가 0 이면 EncoderError."""
    if not vector or any(not math.isfinite(v) for v in vector):
        raise EncoderError("InvalidVector")
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0 or not math.isfinite(norm):
        raise EncoderError("InvalidVector")
    return [v / norm for v in vector]


def validate(vector: list[float], dim: int) -> list[float]:
    """결과 검증: 차원이 맞고 모든 값이 유한하며 길이가 1(정규화됨)이어야 한다. 아니면 EncoderError. 정상이면 같은 벡터."""
    if len(vector) != dim:
        raise EncoderError("DimensionMismatch")
    if any(not math.isfinite(v) for v in vector):
        raise EncoderError("InvalidVector")
    norm = math.sqrt(sum(v * v for v in vector))
    if abs(norm - 1.0) > NORM_TOLERANCE:
        raise EncoderError("NotNormalized")
    return vector


def pack(vector: list[float]) -> bytes:
    """float32 little-endian 바이트(DB `photo_embeddings.vector`)."""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes, dim: int) -> list[float]:
    if len(blob) != dim * 4:
        raise EncoderError("DimensionMismatch")
    return list(struct.unpack(f"<{dim}f", blob))


# ---------- 인코더 ----------
class ImageEncoder(Protocol):
    model_id: str
    model_version: str
    dim: int

    def load(self) -> None: ...

    def encode(self, data: bytes) -> list[float]: ...

    def resources(self) -> dict[str, int | None]: ...


class FakeEncoder:
    """모델이 없는 환경용 결정적 가짜 인코더: 이미지를 4×4 회색조로 줄여 평균을 뺀 값을 정규화한다(같은 입력 → 같은 벡터). 단색 이미지는 바이트 해시로 대신한다."""

    model_id = "fake-gray4x4"
    model_version = "1"
    dim = 16

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def encode(self, data: bytes) -> list[float]:
        if self.fail_with is not None:
            raise self.fail_with
        small = preprocess(data).convert("L").resize((4, 4), Image.Resampling.BOX)
        pixels = [float(p) for p in small.getdata()]
        mean = sum(pixels) / len(pixels)
        centered = [p - mean for p in pixels]
        if not any(centered):  # 단색: 평균을 빼면 0 이라 입력 해시로 방향을 정한다
            import hashlib

            digest = hashlib.sha256(data).digest()
            centered = [float(b) - 127.5 for b in digest[: self.dim]]
        return normalize(centered)

    def resources(self) -> dict[str, int | None]:
        return {"rss_mb": None, "gpu_alloc_mb": None, "gpu_reserved_mb": None}


class Siglip2Encoder:
    """SigLIP2 이미지 인코더(로컬 파일만). `load()` 에서 처음 한 번 모델을 올리고, 이후 `encode()` 는 한 장씩 추론한다."""

    model_id = "siglip2-base-patch16-224"
    dim = 768

    def __init__(self, path: str, device: str = "auto", fp16: bool = False) -> None:
        self.path = path
        self.device_name = device
        self.fp16 = fp16
        self.model_version = "unknown"
        self._torch = None
        self._model = None
        self._processor = None
        self._device = "cpu"

    def load(self) -> None:
        if self._model is not None:
            return
        if not self.path:
            raise EncoderUnavailable("ModelPathMissing")
        import os
        from pathlib import Path

        os.environ["HF_HUB_OFFLINE"] = "1"  # 다운로드 금지: 이미 있는 로컬 파일만 쓴다
        started = time.perf_counter()
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModel
        except Exception as exc:  # noqa: BLE001
            raise EncoderUnavailable(f"Import{type(exc).__name__}"[:40]) from None
        try:
            device = self.device_name
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if (self.fp16 and device == "cuda") else torch.float32
            processor = AutoImageProcessor.from_pretrained(self.path, local_files_only=True)
            model = (
                AutoModel.from_pretrained(self.path, dtype=dtype, local_files_only=True)
                .to(device)
                .eval()
            )
        except Exception as exc:  # noqa: BLE001  모델 파일 없음·손상·메모리 부족
            self._cleanup()
            if _is_oom(exc):
                raise EncoderResourceError("OutOfMemory") from None
            raise EncoderUnavailable(f"Load{type(exc).__name__}"[:40]) from None
        self._torch, self._model, self._processor, self._device = torch, model, processor, device
        self.model_version = (
            Path(self.path).name[:40] or "local"
        )  # 스냅샷 폴더 이름(보통 커밋 해시)
        logger.info(
            "family memory encoder loaded model=%s device=%s fp16=%s load_ms=%d resources=%s",
            self.model_id,
            device,
            dtype == torch.float16,
            int((time.perf_counter() - started) * 1000),
            self.resources(),
        )

    def encode(self, data: bytes) -> list[float]:
        if self._model is None:
            self.load()
        torch = self._torch
        image = preprocess(data)
        try:
            with torch.inference_mode():
                pixel_values = self._processor(images=[image], return_tensors="pt")["pixel_values"]
                pixel_values = pixel_values.to(
                    self._device, dtype=next(self._model.parameters()).dtype
                )
                out = self._model.get_image_features(pixel_values=pixel_values)
                out = out if torch.is_tensor(out) else out.pooler_output
                vector = [float(v) for v in out[0].float().cpu().tolist()]
        except EncoderError:
            raise
        except Exception as exc:  # noqa: BLE001
            if _is_oom(exc):
                self._empty_cache()
                raise EncoderResourceError("OutOfMemory") from None
            raise EncoderError(f"Infer{type(exc).__name__}"[:40]) from None
        return normalize(vector)

    def resources(self) -> dict[str, int | None]:
        info: dict[str, int | None] = {
            "rss_mb": _rss_mb(),
            "gpu_alloc_mb": None,
            "gpu_reserved_mb": None,
        }
        torch = self._torch
        if torch is not None and self._device == "cuda":
            info["gpu_alloc_mb"] = int(torch.cuda.memory_allocated() / 1e6)
            info["gpu_reserved_mb"] = int(torch.cuda.memory_reserved() / 1e6)
        return info

    def _empty_cache(self) -> None:
        try:
            if self._torch is not None and self._device == "cuda":
                self._torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001  정리 실패가 원래 오류를 가리지 않게
            pass

    def _cleanup(self) -> None:
        self._model = self._processor = None
        self._empty_cache()

    def close(self) -> None:
        self._cleanup()


def _is_oom(exc: BaseException) -> bool:
    """GPU 메모리 부족인가(torch.cuda.OutOfMemoryError 또는 같은 뜻의 RuntimeError)."""
    return type(exc).__name__ == "OutOfMemoryError" or "out of memory" in str(exc).lower()


def _rss_mb() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss / 1e6)
    except Exception:  # noqa: BLE001  psutil 이 없으면 기록하지 않는다
        return None
