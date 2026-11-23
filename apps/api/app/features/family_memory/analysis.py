"""AI 추억 사진 임베딩 분석(PR4): PR3 작업 큐 워커에 붙는 처리 함수와 파생 결과 정리 훅.

- **등록은 워커 프로세스에서만**: `register_handlers()` 는 `worker_main`(별도 프로세스)이 부른다. 웹 프로세스는 이 모듈을 불러와도 처리 함수를 등록하지 않고 모델도
  올리지 않으므로 작업을 선점하지 않는다(모델 로드 실패가 채팅·API 에 영향을 주지 않는다).
- 실행: 작업이 선점돼 자격 재확인(PR3 ②③)을 통과한 뒤 사진 파일(채팅이 저장한 EXIF 없는 JPEG)을 읽어 인코더로 임베딩을 만든다. 외부 서비스로 보내지 않는다.
  결과는 **저장 직전 자격 재확인(PR3 ④)을 같은 트랜잭션에서 통과할 때만** `photo_embeddings` 에 저장된다.
- 정리: 동의 철회·가족 나가기·가족 끄기·사진별 제외·사진 삭제 때 그 임베딩을 같은 트랜잭션에서 지운다(훅은 PR3 의 작업 차단 뒤에 불리도록 `job_service` 를 먼저 불러온다:
  진행 중이던 저장이 있으면 작업 줄 잠금 때문에 그 저장이 끝난 뒤에 지워진다).
- 이 모듈은 자동으로 작업을 등록하지 않는다(`job_service.enqueue` 를 부르는 곳은 없다). 로그에는 시간·메모리·예외 종류 이름만 남긴다."""

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.shared import memory_hooks
from app.shared.config import settings

from . import embedding_repository as embeddings
from . import job_repository as jobs
from . import job_service as js  # 훅 등록 순서: 작업 차단 훅이 먼저
from . import worker
from .encoder import (
    EncoderError,
    EncoderUnavailable,
    FakeEncoder,
    ImageEncoder,
    Siglip2Encoder,
    pack,
    validate,
)

logger = logging.getLogger(__name__)

KIND_EMBEDDING = "photo_embedding"
_SAFE_ID = re.compile(r"^[A-Za-z0-9]{1,32}$")
_encoder: ImageEncoder | None = None
_encoder_lock = threading.Lock()


@dataclass(frozen=True)
class EmbeddingResult:
    model_id: str
    model_version: str
    dim: int
    vector: bytes


# ---------- 인코더 ----------
def build_encoder() -> ImageEncoder:
    """설정(`FAMILY_MEMORY_ENCODER`)대로 인코더를 만든다(로드는 하지 않는다). off 이면 EncoderUnavailable."""
    kind = (settings.family_memory_encoder or "off").lower()
    if kind == "fake":
        return FakeEncoder()
    if kind == "siglip2":
        return Siglip2Encoder(
            settings.family_memory_siglip2_path,
            settings.family_memory_encoder_device,
            settings.family_memory_encoder_fp16,
        )
    raise EncoderUnavailable("EncoderOff")


def get_encoder() -> ImageEncoder:
    """프로세스당 한 번 로드한다. 로드에 실패하면 캐시하지 않고 던진다(작업은 재시도 규칙으로 간다)."""
    global _encoder
    with _encoder_lock:
        if _encoder is None:
            encoder = build_encoder()
            encoder.load()
            _encoder = encoder
        return _encoder


def reset_encoder() -> None:
    """시험·재시작용: 캐시한 인코더를 버린다."""
    global _encoder
    with _encoder_lock:
        close = getattr(_encoder, "close", None)
        _encoder = None
    if close:
        close()


# ---------- 처리 함수 ----------
def photo_file(attachment_id: str) -> Path | None:
    """채팅이 저장한 사진 파일 경로(`data_dir/chat_photos/<id>.jpg`, 이름은 서버가 만든 id). 이상한 id 면 None."""
    if not _SAFE_ID.match(attachment_id):
        return None
    return Path(settings.data_dir) / "chat_photos" / f"{attachment_id}.jpg"


def run(job: js.JobView) -> EmbeddingResult:
    """작업 하나의 임베딩을 만든다(DB 를 쓰지 않는다). 사진 파일이 없거나 열 수 없으면 EncoderError, 인코더 로드·추론 실패도 그대로 올린다(재시도 규칙에 맡긴다)."""
    path = photo_file(job.attachment_id)
    if path is None:
        raise EncoderError("InvalidId")
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise EncoderError("PhotoMissing") from None
    encoder = get_encoder()
    started = time.perf_counter()
    vector = validate(encoder.encode(data), encoder.dim)
    logger.info(
        "family memory embedding done kind=%s model=%s dim=%d ms=%d resources=%s",
        job.kind,
        encoder.model_id,
        encoder.dim,
        int((time.perf_counter() - started) * 1000),
        encoder.resources(),
    )
    return EmbeddingResult(encoder.model_id, encoder.model_version, encoder.dim, pack(vector))


def save(db: Session, job: js.JobView, result: EmbeddingResult) -> None:
    """결과를 저장한다. `job_service.complete` 가 행을 잠그고 자격을 다시 확인한 같은 트랜잭션 안에서만 불린다(커밋은 그쪽)."""
    embeddings.upsert(
        db,
        job.group_id,
        job.attachment_id,
        job.user_id,
        result.model_id,
        result.model_version,
        result.dim,
        result.vector,
        datetime.now(UTC),
    )


def register_handlers() -> None:
    """워커 프로세스가 시작할 때만 부른다(웹 프로세스는 부르지 않는다)."""
    worker.register_handler(KIND_EMBEDDING, run, save)


# ---------- 파생 결과 정리 훅 ----------
def _on_member_withdrawn(db: Session, group_id: str, user_id: str) -> None:
    if js._feature_ready():
        embeddings.delete_for_user(db, group_id, user_id)
        jobs.delete_done_for_user(
            db, KIND_EMBEDDING, group_id, user_id
        )  # 재동의 뒤 다시 등록할 수 있게


def _on_family_disabled(db: Session, group_id: str) -> None:
    if js._feature_ready():
        embeddings.delete_for_group(db, group_id)
        jobs.delete_done_for_group(db, KIND_EMBEDDING, group_id)


def _on_photo_excluded(db: Session, group_id: str, attachment_id: str) -> None:
    if js._feature_ready():
        embeddings.delete_for_attachment(db, attachment_id)
        jobs.delete_done_for_attachment(db, KIND_EMBEDDING, attachment_id)


def _on_attachment_removed(db: Session, group_id: str, attachment_id: str) -> None:
    if not js._feature_ready():
        return
    try:
        embeddings.delete_for_attachment(db, attachment_id)
        db.commit()
    except Exception:
        db.rollback()
        raise


memory_hooks.register_member_withdrawn(_on_member_withdrawn)
memory_hooks.register_family_disabled(_on_family_disabled)
memory_hooks.register_photo_excluded(_on_photo_excluded)
memory_hooks.register_attachment_removed(_on_attachment_removed)
