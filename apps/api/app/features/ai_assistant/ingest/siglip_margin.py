"""사진·문서 판별의 SigLIP2 쪽: ONNX 이미지 인코더로 margin 을 구하는 점수기와 판정 규칙. 외부로 사진을 보내지 않고 torch 도 쓰지 않는다
(이미 의존성에 있는 `onnxruntime` CPU 로만 돈다). 로컬 OCR(RapidOCR)은 서비스에서 제거했다(ADR 0025).

규칙(**SigLIP2 단독**. 문장·모델은 공개 데이터 독립 평가 `gabee-classifier-eval/public` 의 동결 설정 exp-1 그대로이고,
임계값은 그 평가의 `T_RESCUE`(5) 를 재사용한다 — 새로 맞춘 값이 아니다):
- margin 이 `T_DOCUMENT`(5) 보다 크면 document, 아니면 unsure. **photo 는 만들지 않는다**(D-13: 일반 사진 확인은 업로더가 한다). 비교는 `>`(초과)다.

근거와 한계(공개 데이터 독립 Test 123장, 문서 42·일반 81, ONNX margin): margin > 5 에서 문서 39/42(재현율 93%)·일반→문서 0/81.
놓친 3장은 글자가 적거나 평범한 문서(margin 2.14·2.89·3.21)로 unsure 가 된다. 소표본이고 **실제 한국어 문서·실제 가족 사진으로는 평가하지 않았다**.

margin = max(문서 문장 6개 logit) - max(일반 문장 8개 logit), logit = exp(logit_scale)*cos + logit_bias (`google/siglip2-base-patch16-224`, sigmoid 없음).
모델 폴더(`PHOTO_CLASSIFY_MODEL_DIR`)에는 변환 산출물 두 개가 있다(저장소에는 올리지 않는다, 변환·검증 방법은 docs/features/ai_assistant-ingest.md):
- `siglip2_vision.onnx`: 비전 타워 + 풀링 헤드, 입력 `pixel_values`(N,3,224,224), 출력 L2 정규화된 이미지 임베딩(N,768)
- `head.json`: 같은 체크포인트·문장·전처리로 미리 계산한 정규화 텍스트 임베딩 14개와 `logit_scale`·`logit_bias`
전처리는 원본과 같다: EXIF 회전 반영 → RGB → 224×224 로 찌그러뜨려 줄이기(BILINEAR) → /255 → 평균·표준편차 0.5.
모델은 처음 사진이 올 때 한 번만 올리고(요청마다 올리지 않는다), 못 올리거나 추론에 실패하면 `MarginError` 다: 호출하는 쪽이 문서·일반 사진으로 확정하지 않고 failed 로 둔다."""

import io
import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

T_DOCUMENT = 5.0  # 평가의 T_RESCUE 값을 재사용한다(SigLIP2 단독 판정의 초기 기준, 바꾸지 않는다)

# 평가에서 쓴 14개 문장(문서 6 + 일반 8). `head.json` 의 문장과 일치해야 로드된다.
DOC_PROMPTS = (
    "a photo of a paper document",
    "a photo of a printed form with a table",
    "a photo of a receipt",
    "a photo of an ID card",
    "a photo of a page of text",
    "a scanned document",
)
PHOTO_PROMPTS = (
    "a photo of a landscape",
    "a photo of food on a plate",
    "a photo of people outdoors",
    "a photo of a menu board",
    "a photo of street signs",
    "a photo of a poster",
    "a photo of a book cover",
    "a photo of a family",
)
MODEL_FILE = "siglip2_vision.onnx"
HEAD_FILE = "head.json"
IMAGE_SIZE = 224
EMBED_DIM = 768
MAX_PIXELS = 25_000_000  # 디코딩 전 크기 검사(압축 폭탄 방어, family_memory 인코더와 같은 상한)
LOAD_RETRY_SECONDS = 30.0  # 로드에 실패했으면 이 시간 동안은 다시 시도하지 않는다(깨진 모델 파일을 사진마다 읽지 않게)


class MarginError(Exception):
    """margin 을 못 구했다. 메시지는 예외 종류 이름만(사진 내용 없음). `Timeout` 이 들어 있으면 앱에 timeout 으로 알려진다."""


class MarginScorer(Protocol):
    def score(self, data: bytes) -> float: ...


def photo_status(margin: float) -> str:
    """SigLIP2 단독 판정: `document` | `unsure`(photo 는 없다)."""
    return "document" if margin > T_DOCUMENT else "unsure"


def model_files_status(folder: str | None) -> str:
    """모델 폴더 상태: `not_configured`(경로 없음) | `missing`(파일 없음) | `present`(두 파일 있음). 파일을 읽지 않는다(해시는 이미지 빌드 때 검증)."""
    if not folder:
        return "not_configured"
    path = Path(folder)
    return (
        "present" if (path / MODEL_FILE).is_file() and (path / HEAD_FILE).is_file() else "missing"
    )


def log_model_status() -> str:
    """서버가 시작할 때 사진 판별 모델 상태를 로그로 알린다(모델 없이 빌드된 이미지를 정상 배포로 오인하지 않게). 경로·사진 내용은 남기지 않는다.
    서버는 로그 설정이 없어 WARNING 이상만 남으므로, 문서 사진 자동 등록이 멈추는 설정(스위치 꺼짐·모델 없음)은 모두 WARNING 으로 남긴다."""
    from app.shared.config import settings

    status = model_files_status(settings.photo_classify_model_dir)
    if status == "present" and settings.photo_classify_siglip:
        logger.info("photo model status=present siglip_switch=True")
    elif settings.photo_classify_siglip:
        logger.warning(
            "photo model status=%s: PHOTO_CLASSIFY_SIGLIP 가 켜져 있지만 모델이 없어 사진 판별이 모두 failed 가 된다",
            status,
        )
    else:
        logger.warning(
            "photo model status=%s: PHOTO_CLASSIFY_SIGLIP 가 꺼져 있어 가족방 사진이 모두 unsure 가 되고 문서 사진 자동 등록이 멈춘다",
            status,
        )
    return status


def margin_from_embedding(embedding, text_embeds, logit_scale: float, logit_bias: float) -> float:
    """정규화된 이미지 임베딩(768)과 정규화된 텍스트 임베딩 14×768 로 margin: logit = exp(scale)·cos + bias, 문서 6개 최댓값 − 일반 8개 최댓값."""
    scale = math.exp(logit_scale)
    logits = [
        scale * sum(float(a) * float(b) for a, b in zip(embedding, row, strict=True)) + logit_bias
        for row in text_embeds
    ]
    return max(logits[: len(DOC_PROMPTS)]) - max(logits[len(DOC_PROMPTS) :])


class OnnxMarginScorer:
    """ONNX 이미지 인코더 점수기. 처음 `score()` 때 모델을 올리고 이후 계속 쓴다(추론은 한 번에 한 장: 순간 메모리를 일정하게 둔다)."""

    def __init__(self, model_dir: str, threads: int = 2) -> None:
        self.model_dir = model_dir
        self.threads = max(int(threads), 1)
        self._lock = threading.Lock()
        self._session = None
        self._text = None  # numpy (14, 768) float32
        self._scale = 0.0
        self._bias = 0.0
        self._failed_until = 0.0
        self._failed_kind = ""

    # -- 로드 --
    def _load(self) -> None:
        if self._session is not None:
            return
        if time.monotonic() < self._failed_until:
            raise MarginError(self._failed_kind)
        started = time.perf_counter()
        try:
            self._load_once()
        except MarginError as exc:
            self._failed_until, self._failed_kind = time.monotonic() + LOAD_RETRY_SECONDS, str(exc)
            raise
        logger.info(
            "photo classify onnx loaded threads=%d load_ms=%d",
            self.threads,
            int((time.perf_counter() - started) * 1000),
        )

    def _load_once(self) -> None:
        if not self.model_dir:
            raise MarginError("ModelDirMissing")
        folder = Path(self.model_dir)
        model_path, head_path = folder / MODEL_FILE, folder / HEAD_FILE
        if not model_path.is_file() or not head_path.is_file():
            raise MarginError("ModelFileMissing")
        try:
            import numpy as np
            import onnxruntime as ort
        except Exception as exc:  # noqa: BLE001
            raise MarginError(f"Import{type(exc).__name__}"[:40]) from None
        try:
            head = json.loads(head_path.read_text(encoding="utf-8"))
            text = np.asarray(head["text_embeds"], dtype=np.float32)
            scale, bias = float(head["logit_scale"]), float(head["logit_bias"])
            if (
                tuple(head["doc_prompts"]) != DOC_PROMPTS
                or tuple(head["photo_prompts"]) != PHOTO_PROMPTS
                or text.shape != (len(DOC_PROMPTS) + len(PHOTO_PROMPTS), EMBED_DIM)
                or not np.isfinite(text).all()
                or not (math.isfinite(scale) and math.isfinite(bias))
            ):
                raise MarginError("HeadMismatch")
            options = ort.SessionOptions()
            options.intra_op_num_threads = self.threads
            options.inter_op_num_threads = 1
            options.enable_cpu_mem_arena = False  # 추론마다 쓴 메모리를 돌려줘 상주 메모리를 낮춘다
            options.log_severity_level = 3
            session = ort.InferenceSession(
                str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        except MarginError:
            raise
        except MemoryError:
            raise MarginError("OutOfMemory") from None
        except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
            raise MarginError(f"Load{type(exc).__name__}"[:40]) from None
        self._session, self._text, self._scale, self._bias = session, text, scale, bias

    # -- 전처리·점수 --
    @staticmethod
    def preprocess(data: bytes):
        """사진 바이트 → (1,3,224,224) float32. 열 수 없거나 너무 크면 MarginError."""
        import numpy as np
        from PIL import Image, ImageOps

        try:
            with Image.open(io.BytesIO(data)) as opened:
                if opened.width * opened.height > MAX_PIXELS:
                    raise MarginError("ImageTooLarge")
                image = ImageOps.exif_transpose(opened).convert("RGB")
            image = image.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR)
        except MarginError:
            raise
        except MemoryError:
            raise MarginError("OutOfMemory") from None
        except Exception:  # noqa: BLE001
            raise MarginError("InvalidImage") from None
        array = np.asarray(image, dtype=np.float32) / 255.0
        array = (array - 0.5) / 0.5
        return np.ascontiguousarray(array.transpose(2, 0, 1)[None, ...])

    def score(self, data: bytes) -> float:
        pixels = self.preprocess(data)
        with self._lock:
            self._load()
            try:
                embedding = self._session.run(None, {"pixel_values": pixels})[0][0]
            except MemoryError:
                raise MarginError("OutOfMemory") from None
            except Exception as exc:  # noqa: BLE001
                raise MarginError(f"Infer{type(exc).__name__}"[:40]) from None
        try:
            margin = margin_from_embedding(embedding, self._text, self._scale, self._bias)
        except Exception as exc:  # noqa: BLE001
            raise MarginError(f"Infer{type(exc).__name__}"[:40]) from None
        if not math.isfinite(margin):
            raise MarginError("InferNonFinite")
        return float(margin)

    def close(self) -> None:
        with self._lock:
            self._session = None


_scorer: MarginScorer | None = None
_scorer_lock = threading.Lock()


def get_scorer() -> MarginScorer:
    """설정(`PHOTO_CLASSIFY_MODEL_DIR`·`PHOTO_CLASSIFY_THREADS`)으로 만든 공용 점수기(처음 부를 때 한 번 만든다. 모델은 첫 사진에서 올라간다)."""
    global _scorer
    with _scorer_lock:
        if _scorer is None:
            from app.shared.config import settings

            _scorer = OnnxMarginScorer(
                settings.photo_classify_model_dir, settings.photo_classify_threads
            )
        return _scorer


def set_scorer(scorer: MarginScorer | None) -> None:
    """시험·교체용: 공용 점수기를 바꾼다(None 이면 다음에 설정으로 다시 만든다)."""
    global _scorer
    with _scorer_lock:
        _scorer = scorer
