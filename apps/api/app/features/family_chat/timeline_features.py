"""가족 타임라인용 사진 분석 결과(문서 margin·이미지 임베딩)의 저장·조회·예약. **DB 스키마를 바꾸지 않는다**: 결과는 사진 파일 옆의 작은 JSON 파일이다.

- 위치: settings.data_dir/chat_photos/<첨부 id>_sig.json (성공), <첨부 id>_sigfail.json (실패 종류와 시각). 파일 이름은 서버가 만든 id 로만 정한다.
- 분석은 사진마다 한 번이다(캐시): 성공 결과가 있으면 다시 추론하지 않는다. 캐시 파일이 사라지면(컨테이너 로컬 디스크가 비영속이면) 같은 원본에서 다시 만든다 —
  원본(`chat_photos/<id>.jpg`)도 사라졌다면 `OriginalMissing` 실패로 남고 복구되지 않는다(영속 저장소 없이는 보장하지 못한다).
- 추론은 요청 안에서 하지 않는다: 업로드 직후와 타임라인 조회 때 **한 번에 최대 `BACKFILL_PER_REQUEST` 장**만 전용 스레드 하나(`max_workers=1`)에 맡기고,
  대기가 `MAX_QUEUE` 를 넘으면 거절한다(다음 조회 때 다시 맡긴다). 요청은 결과를 기다리지 않는다.
- 외부 서비스·LLM 호출은 없다. 분석 함수는 `shared/image_features` 가 로컬 SigLIP2(ONNX)로 이어 준다.
- 문서 후보(`margin > DOC_MARGIN`)와 분석 실패·미분석 사진은 **자동 후보가 아니다**(타임라인에 나오지 않는다). 분석 실패는 `RETRY_FAILED_AFTER` 뒤에 다시 시도한다.
- **켜는 조건(ADR 0026)**: 서버 스위치 `TIMELINE_AUTO_CANDIDATES`(기본 꺼짐)가 켜져 있고, 사진마다 ADR 0020 의 3중 조건과 분석 제외를
  만족해야(`shared/photo_analysis_consent`) 분석·임베딩 사용·자동 노출을 한다. 꺼져 있으면 이 모듈은 아무것도 분석하지 않는다(부르는 쪽이 `enabled()` 로 먼저 거른다)."""

import json
import logging
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.shared import image_features
from app.shared.config import settings

logger = logging.getLogger(__name__)

DOC_MARGIN = 5.0  # margin 이 이보다 크면 문서 후보(타임라인 자동 후보에서 뺀다). 문서 판별 정확도가 입증됐다는 뜻이 아니다
EMBED_DIM = 768
BACKFILL_PER_REQUEST = 40  # 타임라인 조회 한 번이 새로 맡기는 사진 수 상한(실측 사진 1장 ≈0.22초: 한 번에 약 9초 분량. 대기열 상한 MAX_QUEUE 의 절반 이하라서 두 요청이 겹쳐도 넘치지 않는다)
MAX_QUEUE = (
    100  # 인스턴스 전체에서 분석을 기다리는 사진 수 상한(넘으면 거절하고 다음 조회 때 다시 맡긴다)
)
RETRY_FAILED_AFTER = 600.0  # 분석 실패 뒤 다시 시도하기까지 초
WINDOW_CAP = 3000  # 한 번에 훑는 최근 사진 수 상한(요청이 무한정 무거워지지 않게). 이보다 오래된 사진은 이 MVP 의 타임라인에 나오지 않는다(한계)
_CACHE_MAX = 4000  # 메모리에 두는 임베딩 수(가족 여러 곳의 최근 사진)


def enabled() -> bool:
    """타임라인 이미지 분석(자동 후보·유사 묶기) 서버 스위치. 기본 꺼짐(ADR 0026)."""
    return bool(settings.timeline_auto_candidates)


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="timeline-sig")
_lock = threading.Lock()
_inflight: set[str] = set()
_cache: "OrderedDict[str, Features]" = OrderedDict()
_revoked: "OrderedDict[str, float]" = (
    OrderedDict()
)  # forget 한 시각(그 전에 시작한 작업이 결과를 되살리지 않게)
_REVOKED_MAX = 20000
_write_guard: "Callable[[str], bool] | None" = None


@dataclass(frozen=True)
class Features:
    margin: float
    embedding: tuple[float, ...]

    @property
    def is_candidate(self) -> bool:
        """문서 후보가 아니면 타임라인 자동 후보다."""
        return self.margin <= DOC_MARGIN


def _dir() -> Path:
    return Path(settings.data_dir) / "chat_photos"


def _sig_path(attachment_id: str) -> Path:
    return _dir() / f"{attachment_id}_sig.json"


def _fail_path(attachment_id: str) -> Path:
    return _dir() / f"{attachment_id}_sigfail.json"


def _safe_id(attachment_id: str) -> bool:
    return bool(attachment_id) and attachment_id.isalnum() and len(attachment_id) <= 32


def load(attachment_id: str) -> Features | None:
    """저장된 분석 결과. 없거나 깨졌거나 모양이 다르면 None(미분석으로 본다)."""
    if not _safe_id(attachment_id):
        return None
    with _lock:
        hit = _cache.get(attachment_id)
        if hit is not None:
            _cache.move_to_end(attachment_id)
            return hit
    try:
        raw = json.loads(_sig_path(attachment_id).read_text(encoding="utf-8"))
        margin = float(raw["margin"])
        emb = tuple(float(v) for v in raw["emb"])
        if raw.get("v") != 1 or len(emb) != EMBED_DIM or not math.isfinite(margin):
            return None
        if not all(math.isfinite(v) for v in emb):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    found = Features(margin, emb)
    with _lock:
        _cache[attachment_id] = found
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return found


def failure(attachment_id: str) -> tuple[str, float] | None:
    """분석 실패 기록 (종류 이름, 실패 시각 epoch 초). 없으면 None."""
    if not _safe_id(attachment_id):
        return None
    try:
        raw = json.loads(_fail_path(attachment_id).read_text(encoding="utf-8"))
        return str(raw["kind"])[:40], float(raw["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def set_write_guard(fn: Callable[[str], bool] | None) -> None:
    """분석 결과를 파일에 쓰기 직전에 다시 확인하는 함수(첨부 id → 지금도 분석해도 되는가)를 등록한다.
    작업이 대기하는 사이 동의 철회·가족 비활성화·분석 제외·메시지 삭제가 일어나면 결과를 쓰지 않는다(파생 데이터가 되살아나지 않게)."""
    global _write_guard
    _write_guard = fn


def forget(attachment_id: str) -> None:
    """첨부를 지우거나 분석 자격이 사라질 때 분석 결과·실패 기록·쓰다 남은 임시 파일과 메모리 캐시를 지운다(실패해도 던지지 않는다).
    지운 시각을 남겨, 그 전에 시작한 분석 작업이 끝나도 결과를 다시 쓰지 않게 한다."""
    if not _safe_id(attachment_id):
        return
    with _lock:
        _cache.pop(attachment_id, None)
        _revoked[attachment_id] = time.time()
        while len(_revoked) > _REVOKED_MAX:
            _revoked.popitem(last=False)
    for path in (_sig_path(attachment_id), _fail_path(attachment_id)):
        for target in (path, path.with_suffix(path.suffix + ".tmp")):
            try:
                target.unlink(missing_ok=True)
            except OSError:
                logger.warning("timeline features cleanup failed")


def _kind(exc: Exception) -> str:
    """실패 종류 이름만(사진 내용·경로 없음). 우리 분석 예외는 메시지가 종류 이름이다."""
    if type(exc).__name__ in ("MarginError", "FeaturesUnavailable"):
        return str(exc)[:40] or type(exc).__name__
    return type(exc).__name__[:40]


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def analyze_attachment(attachment_id: str) -> bool:
    """사진 하나를 분석해 저장한다(스레드에서 부른다). 성공하면 True. 어떤 실패도 던지지 않고 실패 기록만 남긴다.
    쓰기 직전에 (1) 이 작업이 시작된 뒤 `forget` 이 불렸는지 (2) 등록된 확인 함수로 지금도 분석해도 되는지 다시 보고, 아니면 쓰지 않는다."""
    started = time.time()
    try:
        original = _dir() / f"{attachment_id}.jpg"
        try:
            data = original.read_bytes()
        except OSError:
            raise image_features.FeaturesUnavailable("OriginalMissing") from None
        margin, emb = image_features.analyze(data)
        if len(emb) != EMBED_DIM or not math.isfinite(margin):
            raise image_features.FeaturesUnavailable("BadFeatures")
        if not _may_write(attachment_id, started):
            logger.info("timeline analyze dropped: no longer allowed")
            return False
        _write_atomic(
            _sig_path(attachment_id),
            json.dumps(
                {
                    "v": 1,
                    "margin": round(float(margin), 4),
                    "emb": [round(float(v), 5) for v in emb],
                }
            ),
        )
        try:
            _fail_path(attachment_id).unlink(missing_ok=True)
        except OSError:
            pass
        with _lock:
            _cache.pop(attachment_id, None)
        return True
    except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        kind = _kind(exc)
        logger.warning("timeline analyze failed kind=%s", kind)
        try:
            _write_atomic(_fail_path(attachment_id), json.dumps({"kind": kind, "at": time.time()}))
        except OSError:
            pass
        return False


def _may_write(attachment_id: str, started: float) -> bool:
    with _lock:
        revoked_at = _revoked.get(attachment_id)
    if revoked_at is not None and revoked_at >= started:
        return False  # 작업이 도는 사이 지웠다(철회·삭제)
    guard = _write_guard
    if guard is None:
        return True
    try:
        return bool(guard(attachment_id))
    except Exception as exc:  # noqa: BLE001  확인 실패는 쓰지 않는 쪽
        logger.warning("timeline write guard failed kind=%s", type(exc).__name__)
        return False


def _run(attachment_id: str) -> None:
    try:
        analyze_attachment(attachment_id)
    finally:
        with _lock:
            _inflight.discard(attachment_id)


def schedule(attachment_ids: Iterable[str]) -> int:
    """아직 분석하지 않은 사진을 전용 스레드에 맡긴다(기다리지 않는다). 이미 맡겼거나 큐가 가득 찼으면 건너뛴다. 맡긴 수를 돌려준다."""
    accepted = 0
    for attachment_id in attachment_ids:
        if not _safe_id(attachment_id):
            continue
        with _lock:
            if attachment_id in _inflight or len(_inflight) >= MAX_QUEUE:
                continue
            _inflight.add(attachment_id)
        try:
            _executor.submit(_run, attachment_id)
            accepted += 1
        except Exception as exc:  # noqa: BLE001  서버를 끄는 중이면 작업이 들어가지 않는다
            with _lock:
                _inflight.discard(attachment_id)
            logger.warning("timeline analyze submit failed kind=%s", type(exc).__name__)
    return accepted


@dataclass(frozen=True)
class CandidateState:
    eligible: dict[str, Features]  # 문서 후보가 아닌, 분석이 끝난 자동 후보
    analyzing: int  # 분석 전이거나 진행 중(타임라인에 아직 없음)
    failed: int  # 분석 실패(재시도 대기, 타임라인에 없음)


def classify_candidates(
    attachment_ids: list[str], now: float | None = None, backfill: bool = True
) -> CandidateState:
    """자동 후보 사진들의 분석 상태를 나눈다. `backfill` 이면 분석 전이거나 재시도 시간이 지난 사진을 최대 `BACKFILL_PER_REQUEST` 장 맡긴다."""
    now = now if now is not None else time.time()
    eligible: dict[str, Features] = {}
    todo: list[str] = []
    analyzing = failed = 0
    for att in attachment_ids:
        found = load(att)
        if found is not None:
            if found.is_candidate:
                eligible[att] = found
            continue  # 문서 후보는 자동 후보가 아니다(세지도 않는다)
        bad = failure(att)
        if bad is None:
            analyzing += 1
            todo.append(att)
        elif now - bad[1] >= RETRY_FAILED_AFTER:
            failed += 1  # 재시도 시간이 지났다: 다시 맡긴다(그동안은 실패로 보인다)
            todo.append(att)
        else:
            failed += 1
    if backfill and todo:
        schedule(todo[:BACKFILL_PER_REQUEST])
    return CandidateState(eligible, analyzing, failed)
