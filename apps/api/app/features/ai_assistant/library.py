"""가족 채팅에 올린 문서를 가족 공유 문서함(knowledge)에 자동 등록한다(`shared/chat_library.py` 통로의 처리 쪽).

- 가족 전체방의 문서 첨부만 온다. 민감 문서(처방전·신분증 등)도 등록한다(2026-11-09 사용자 결정): 기록에 민감 표시가 붙고, 그 문서의 챙길 일 뽑기는 건너뛴다.
- ingest 가 지원하지 않는 형식(hwp·hwpx·예전 doc/xls/ppt 등)은 읽기 전에 거르고 보관하지도 않는다(채팅 파일로만 남는다).
- 같은 첨부는 한 번만(`knowledge_items.source_attachment_id` 유일). 읽기·저장은 기존 업로드 뒷처리(`files.process_file`)를 그대로 쓴다:
  `photos` 행을 만들고 knowledge 기록 id 를 그 id 와 같게 둬서 상태·원본 보기·삭제가 기존 문서와 똑같이 동작한다.
- 채팅 메시지를 지우면 연결된 기록·원본도 함께 지운다(`files.delete_record`)."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.shared import ai_guard, chat_library
from app.shared.config import settings
from app.shared.db import SessionLocal

from . import files, service
from . import repository as repo
from .ingest import siglip_margin
from .ingest.detect import Unsupported, detect
from .ingest.service import chat_masking_blocked
from .knowledge import repository as knowledge_repo

logger = logging.getLogger(__name__)

# 읽기(OCR)는 CPU 를 쓰므로 채팅 전송과 따로, 한 번에 둘까지만(files.process_file 안의 칸도 둘이다)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-library")


_jobs_lock = threading.Lock()
_jobs: dict[
    int, dict
] = {}  # 아직 끝나지 않은 응답 뒤 작업(관측·종료 처리용. 영속 큐가 아니다: 프로세스가 죽으면 사라진다)


def _submit(fn, *args) -> None:
    """등록을 백그라운드에서 실행한다(시험은 이 함수를 그 자리 실행으로 바꾼다).
    끝나지 않은 작업을 추적해서 대기·진행 건수를 볼 수 있고(`queue_stats`), 서버를 끄기 전에 아직 시작하지 않은 작업을 취소할 수 있다(`cancel_queued_jobs`).
    이 추적은 **완료를 보장하지 않는다**: 진행 중이거나 대기 중인 작업은 프로세스가 강제 종료되면 그대로 사라진다."""
    job: dict = {"fn": fn, "started": False}

    def run_tracked() -> None:
        with _jobs_lock:
            job["started"] = True
        try:
            fn(*args)
        finally:
            with _jobs_lock:
                _jobs.pop(id(job), None)

    with _jobs_lock:
        _jobs[id(job)] = job
    try:
        job["future"] = _executor.submit(run_tracked)
    except Exception:
        with _jobs_lock:
            _jobs.pop(id(job), None)
        raise


def queue_stats() -> dict[str, int]:
    """응답 뒤 작업의 대기(아직 시작하지 않음)·진행 건수. 개인정보 없이 숫자만."""
    with _jobs_lock:
        started = sum(1 for j in _jobs.values() if j["started"])
        return {"queued": len(_jobs) - started, "running": started}


def cancel_queued_jobs() -> dict[str, int]:
    """서버를 끄기 전에 아직 시작하지 않은 작업을 취소한다(진행 중인 작업은 건드리지 않는다). 취소한 사진 판별 작업은 사진이 `pending` 으로
    남아 15분을 기다리지 않도록 `failed`(종류 `Shutdown`)로 적어 업로더가 바로 다시 검사할 수 있게 한다. 원본이 영속 저장소에 없으면 다시 검사해도 복구는 보장되지 않는다.
    executor 자체는 닫지 않는다(시험·재시작 경로에서 계속 쓸 수 있게). 돌려주는 값은 건수만이다."""
    with _jobs_lock:
        waiting = [j for j in _jobs.values() if not j["started"]]
        running = len(_jobs) - len(waiting)
    cancelled = 0
    for job in waiting:
        future = job.get("future")
        if future is None or not future.cancel():  # 그 사이 시작했으면 취소되지 않는다
            continue
        cancelled += 1
        with _jobs_lock:
            _jobs.pop(id(job), None)
        on_cancel = getattr(job["fn"], "on_cancel", None)
        if on_cancel is not None:
            try:
                on_cancel()
            except Exception as exc:  # noqa: BLE001  종료를 막지 않는다(종류만 기록)
                logger.warning("chat library cancel cleanup failed error=%s", type(exc).__name__)
    return {"cancelled": cancelled, "running": running}


def startup_report() -> None:
    """기동 때 이전 프로세스가 끝내지 못한 것으로 보이는 작업 수를 로그로 남긴다(숫자만, 읽기 전용: 상태를 바꾸지 않아 여러 인스턴스가 있어도 안전하다).
    이것은 **관측**일 뿐 복구가 아니다: 메모리 대기열과 읽던 내용은 사라졌고, 원본이 영속 저장소에 없으면 다시 처리할 수 없다.
    DB 가 아직 준비되지 않았어도 기동을 막지 않는다."""
    try:
        received = stale_received_count()
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat library startup report failed error=%s", type(exc).__name__)
        received = None
    pending = chat_library.stale_pending_photo_count()
    if received or pending:
        logger.warning(
            "chat library unfinished work found at startup stale_received=%s stale_pending_photos=%s",
            received,
            pending,
        )
    else:
        logger.info(
            "chat library startup: no stale work (received=%s pending=%s)", received, pending
        )


def shutdown_report() -> dict[str, int]:
    """서버를 끌 때 아직 시작하지 않은 작업을 취소하고(사진 판별은 failed `Shutdown` 으로 적는다) 건수를 로그로 남긴다. 진행 중인 작업의 완료는 보장하지 않는다."""
    result = cancel_queued_jobs()
    if result["cancelled"] or result["running"]:
        logger.warning(
            "chat library shutdown: cancelled_queued=%d running_may_be_lost=%d",
            result["cancelled"],
            result["running"],
        )
    return result


def stale_received_count(older_than: timedelta = files.STUCK_AFTER) -> int:
    """오래도록 `received` 로 남은 업로드(읽던 중 서버가 죽었을 가능성) 수. 읽기만 하고 바꾸지 않는다(여러 인스턴스가 있어도 안전)."""
    with SessionLocal() as db:
        return repo.count_stale_received(db, datetime.now(UTC) - older_than)


def supported(data: bytes, filename: str) -> bool:
    """ingest 가 읽을 수 있는 형식인지(예전 형식·알 수 없는 형식은 등록하지 않는다)."""
    try:
        detect(data, filename)
    except Unsupported:
        return False
    return True


def register_chat_document(
    group_id: str,
    user_id: str,
    attachment_id: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> None:
    """채팅 문서 첨부 하나를 문서함에 등록한다(읽기 → 저장, 민감 문서는 민감 표시를 붙여 저장). 어떤 실패도 던지지 않는다."""
    try:
        if not supported(data, filename):
            return
        if chat_masking_blocked(True):
            # Claude 가리기가 꺼져 있으면 로컬 규칙으로만 가린 문서가 되므로 등록하지 않는다(채팅 첨부는 그대로). 외부 호출도 시작하지 않는다
            logger.info("chat library document held: masking unavailable")
            return
        if not _family_allows_ai(group_id):
            # 가족 AI 동의가 없으면 AI 문서함 자동 등록을 **보류**한다(사용자 결정 2026-11-23, ADR 0024): 채팅 원본 첨부는 그대로 두고, 외부 AI(Claude·Jev)도
            # 부르지 않으며, 로컬 규칙으로만 가린 문서를 AI 검색 지식베이스에 넣지도 않는다. 동의한 뒤에는 사용자가 파일을 다시 올려 명시적으로 처리한다.
            logger.info("chat library document held: no family AI consent")
            return
        with SessionLocal() as db:
            if knowledge_repo.get_by_attachment(db, group_id, attachment_id) is not None:
                return  # 이미 등록했다(재시도·중복 요청)
            if not chat_library.attachment_exists(db, group_id, attachment_id):
                return  # 대기하는 사이 메시지가 지워졌다
            photo = service.receive_file(db, group_id, user_id, filename, content_type, data)
            photo_id = photo.id
        files.process_file(
            photo_id,
            group_id,
            user_id,
            data,
            filename,
            source_attachment_id=attachment_id,
            purpose=files.Purpose.FAMILY_CHAT_DOCUMENT,
        )
    except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        logger.warning("chat library register failed error=%s", type(exc).__name__)


def _on_document(
    group_id: str, user_id: str, attachment_id: str, filename: str, content_type: str, data: bytes
) -> None:
    _submit(register_chat_document, group_id, user_id, attachment_id, filename, content_type, data)


def _on_removed(db: Session, group_id: str, attachment_id: str) -> None:
    item = knowledge_repo.get_by_attachment(db, group_id, attachment_id)
    if item is not None:
        files.delete_record(db, group_id, item.id)


# ---------- 사진 ----------

PHOTO_QUEUE_LIMIT = 20  # 가족마다 처리를 기다리는 사진 수(사진 바이트가 메모리에 있으므로 상한을 둔다). 한 가족이 다른 가족을 막지 않는다
PHOTO_QUEUE_INSTANCE_LIMIT = 40  # 서버 인스턴스 전체에서 처리를 기다리는 사진 수(가족마다 20장씩 여러 가족이 쌓여도 메모리가 늘지 않게)
PHOTO_QUEUE_INSTANCE_BYTES = (
    96 * 1024 * 1024
)  # 서버 인스턴스 전체에서 기다리는 사진 바이트 합(사진 한 장 최대 8MB)
_photo_lock = threading.Lock()
_photo_pending: dict[str, int] = {}  # 가족 → 처리를 기다리는 사진 수
_photo_bytes = 0  # 인스턴스 전체에서 기다리는 사진 바이트 합(직접 저장 포함)
_photo_inflight: set[tuple[str, str, bool]] = (
    set()
)  # (가족, 첨부, 직접 저장 여부) 진행 중인 것: 같은 요청을 겹쳐 처리하지 않는다


def _family_allows_ai(group_id: str) -> bool:
    """가족 그룹이 AI 사용에 동의했는지(외부 AI 는 동의한 가족에게만 쓴다)."""
    with SessionLocal() as db:
        return ai_guard.is_enabled(db, group_id)


def _judge_photo(group_id: str, data: bytes) -> tuple[str, str | None]:
    """사진 판별 결과 (상태, 실패 종류). 상태는 document | unsure | failed 셋 중 하나다(**photo 는 없다**: 모델 판정만으로 일반 사진을
    확정하지 않는다. 일반 사진 확인은 업로더가 직접 한다, D-13). 판별은 **로컬 SigLIP2 ONNX 단독**이고(margin > 5 이면 document,
    아니면 unsure) 사진을 외부(Claude)로 보내지 않는다. 로컬 OCR(RapidOCR)은 쓰지 않는다.
    `PHOTO_CLASSIFY_SIGLIP` 가 꺼져 있으면 판별 수단이 없어서 모든 사진이 unsure 다(문서 자동 등록이 멈춘다: 켜야 동작한다).
    점수를 못 구하면(모델 파일·로드·메모리·추론 오류) 문서·일반 사진으로 확정하지 않고 failed 다(기존 재검사 규칙을 따른다).
    하루 상한은 없다(2026-11-09 사용자 결정)."""
    if not settings.photo_classify_siglip:
        return "unsure", None
    try:
        margin = siglip_margin.get_scorer().score(data)
    except siglip_margin.MarginError as exc:
        logger.warning("chat library photo siglip failed error=%s", exc)
        return "failed", f"Siglip{exc}"[:40]
    except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        logger.warning("chat library photo siglip failed error=%s", type(exc).__name__)
        return "failed", f"Siglip{type(exc).__name__}"[:40]
    return siglip_margin.photo_status(margin), None


def register_chat_photo(
    group_id: str, user_id: str, attachment_id: str, data: bytes, forced: bool = False
) -> None:
    """채팅 사진 하나를 판별해서 문서 사진이면 문서함에 등록한다(읽기 → 저장, 민감 문서는 민감 표시를 붙여 저장). 어떤 실패도 던지지 않는다.
    forced 는 사용자가 직접 저장을 눌러 판별을 건너뛰는 경우다."""
    try:
        if chat_masking_blocked(True):
            # 판별 상태도 바꾸지 않고(사진은 채팅에 남는다) 로컬 규칙으로만 가린 문서를 만들지 않는다
            logger.info("chat library photo held: masking unavailable")
            return
        with SessionLocal() as db:
            if knowledge_repo.get_by_attachment(db, group_id, attachment_id) is not None:
                return
            if not chat_library.attachment_exists(db, group_id, attachment_id):
                return
        if not forced:
            status, error = _judge_photo(group_id, data)
            if status == "document" and not _family_allows_ai(group_id):
                # 문서 글자는 Claude 로만 읽으므로(로컬 OCR 없음), 가족 AI 동의가 없으면 사진을 외부로 보내지 않는다: 문서 자동 등록은
                # 보류하고 사진은 채팅에 남긴다. 숨기지 않게 document 가 아니라 unsure 로 적어 업로더가 직접 확인한다.
                status = "unsure"
            # 결과를 판별 상태 표에 적는다(문서함 등록보다 먼저: 문서면 바로 숨김 상태가 된다). 못 적어도 pending 으로 남아 안전하다
            may_register = chat_library.photo_judged(group_id, attachment_id, status, error)
            if status != "document":
                return
            if not may_register:
                return  # 업로더가 이미 일반 사진으로 확인한 사진: 문서함에 올리면 타임라인과 문서함에 둘 다 있게 된다(b0-2a 리뷰)
            with SessionLocal() as db:
                if not chat_library.attachment_exists(db, group_id, attachment_id):
                    return  # 판별하는 사이 메시지가 지워졌다: 지운 사진이 문서함에 남지 않게(재검사처럼 오래 걸리는 판별 뒤의 경합)
        elif not _family_allows_ai(group_id):
            return  # 직접 저장도 같다: 동의 없이는 사진을 Claude 로 읽지 않는다(라우터가 먼저 403 으로 막는다. 이 줄은 동의가 도중에 꺼진 경우의 방어)
        with SessionLocal() as db:
            photo = service.receive_file(
                db, group_id, user_id, f"{attachment_id}.jpg", "image/jpeg", data
            )
            photo_id = photo.id
        files.process_file(
            photo_id, group_id, user_id, data, f"{attachment_id}.jpg",
            source_attachment_id=attachment_id, keep_photo=forced or settings.photo_classify_siglip,
            purpose=files.Purpose.FAMILY_CHAT_DOCUMENT,
        )  # fmt: skip
        # 단계형(E)이 켜져 있으면 문서로 판정된 사진은 글자가 적어도 문서함에 남긴다: 글자가 적은 문서를 SigLIP2 가 구한 경우(rescue)를 읽기 단계가
        # 다시 "사진"으로 버리면, 판별 상태는 document 인데 문서함에는 없는 채로 업로더가 일반 사진 확인도 못 하게 된다.
    except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        logger.warning("chat library photo register failed error=%s", type(exc).__name__)


def _on_photo(
    group_id: str, user_id: str, attachment_id: str, data: bytes, forced: bool = False
) -> None:
    global _photo_bytes
    key = (group_id, attachment_id, forced)
    full = False
    with _photo_lock:
        if key in _photo_inflight:
            return  # 같은 요청이 이미 처리 중이다(연타·재요청)
        if not forced and (
            _photo_pending.get(group_id, 0) >= PHOTO_QUEUE_LIMIT
            or sum(_photo_pending.values()) >= PHOTO_QUEUE_INSTANCE_LIMIT
            or _photo_bytes + len(data) > PHOTO_QUEUE_INSTANCE_BYTES
        ):
            full = True  # 직접 누른 저장은 버리지 않는다(요청 횟수는 라우터가 제한한다)
        else:
            _photo_pending[group_id] = _photo_pending.get(group_id, 0) + 1
            _photo_bytes += len(data)
            _photo_inflight.add(key)
    if full:
        # 가족·인스턴스 건수나 바이트 상한을 넘었다: 이번 사진은 건너뛰되, 15분 동안 조용히 pending 으로 두지 않고 failed(`QueueFull`)로 적어
        # 업로더가 "확인 필요" 목록에서 바로 다시 검사할 수 있게 한다(이미 정해진 줄은 바뀌지 않는다). 원본 파일이 남아 있어야 다시 검사가 된다.
        logger.info("chat library photo queue full")
        chat_library.photo_judged(group_id, attachment_id, "failed", "QueueFull")
        return

    def release() -> None:
        global _photo_bytes
        with _photo_lock:
            _photo_bytes = max(0, _photo_bytes - len(data))
            _photo_inflight.discard(key)
            left = _photo_pending.get(group_id, 1) - 1
            if left > 0:
                _photo_pending[group_id] = left
            else:
                _photo_pending.pop(group_id, None)

    def run() -> None:
        try:
            register_chat_photo(group_id, user_id, attachment_id, data, forced)
        finally:
            release()

    if not forced:

        def on_cancel() -> None:
            """서버를 끄기 전에 시작하지 못하고 취소된 판별: 자리를 되돌리고 사진을 failed(`Shutdown`)로 적어 바로 다시 검사할 수 있게 한다."""
            release()
            chat_library.photo_judged(group_id, attachment_id, "failed", "Shutdown")

        run.on_cancel = on_cancel  # type: ignore[attr-defined]  # `_submit` 이 취소할 때 부른다

    try:
        _submit(run)
    except Exception as exc:  # noqa: BLE001  서버를 끄는 중이면 작업이 들어가지 않는다: 자리를 되돌린다
        release()
        if not forced:
            chat_library.photo_judged(group_id, attachment_id, "failed", "SubmitFailed")
        logger.warning("chat library photo submit failed error=%s", type(exc).__name__)


def _photo_registered(db: Session, group_id: str, attachment_id: str) -> bool:
    return knowledge_repo.get_by_attachment(db, group_id, attachment_id) is not None


def _photos_registered(db: Session, group_id: str, attachment_ids: list[str]) -> set[str]:
    return knowledge_repo.registered_attachment_ids(db, group_id, attachment_ids)


def register() -> None:
    """ai_assistant 가 시작할 때 처리 함수를 채팅 쪽 통로에 등록한다."""
    chat_library.register_handlers(_on_document, _on_removed)
    chat_library.register_photo_handler(_on_photo, _photo_registered, _photos_registered)
