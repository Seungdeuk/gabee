"""가족 채팅에 올린 문서를 가족 공유 문서함(knowledge)에 자동 등록한다(`shared/chat_library.py` 통로의 처리 쪽).

- 가족 전체방의 문서 첨부만 온다. **민감 문서(처방전·신분증 등)는 등록하지 않고** 가리기 전 원본 사본도 남기지 않는다.
- ingest 가 지원하지 않는 형식(hwp·hwpx·예전 doc/xls/ppt 등)은 읽기 전에 거르고 보관하지도 않는다(채팅 파일로만 남는다).
- 같은 첨부는 한 번만(`knowledge_items.source_attachment_id` 유일). 읽기·저장은 기존 업로드 뒷처리(`files.process_file`)를 그대로 쓴다:
  `photos` 행을 만들고 knowledge 기록 id 를 그 id 와 같게 둬서 상태·원본 보기·삭제가 기존 문서와 똑같이 동작한다.
- 채팅 메시지를 지우면 연결된 기록·원본도 함께 지운다(`files.delete_record`)."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from sqlalchemy.orm import Session

from app.shared import chat_library
from app.shared.db import SessionLocal

from . import files, service
from .ingest import photo_judge
from .ingest.detect import Unsupported, detect
from .knowledge import repository as knowledge_repo

logger = logging.getLogger(__name__)

# 읽기(OCR)는 CPU 를 쓰므로 채팅 전송과 따로, 한 번에 둘까지만(files.process_file 안의 칸도 둘이다)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-library")


def _submit(fn, *args) -> None:
    """등록을 백그라운드에서 실행한다(시험은 이 함수를 그 자리 실행으로 바꾼다)."""
    _executor.submit(fn, *args)


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
    """채팅 문서 첨부 하나를 문서함에 등록한다(읽기 → 민감하지 않으면 저장). 어떤 실패도 던지지 않는다."""
    try:
        if not supported(data, filename):
            return
        with SessionLocal() as db:
            if knowledge_repo.get_by_attachment(db, group_id, attachment_id) is not None:
                return  # 이미 등록했다(재시도·중복 요청)
            if not chat_library.attachment_exists(db, group_id, attachment_id):
                return  # 대기하는 사이 메시지가 지워졌다
            photo = service.receive_file(db, group_id, user_id, filename, content_type, data)
            photo_id = photo.id
        files.process_file(
            photo_id, group_id, user_id, data, filename, source_attachment_id=attachment_id
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

PHOTO_DAILY_LIMIT = (
    30  # 가족당 하루에 자동으로 읽는 문서 사진 수(Claude 읽기 비용 상한). 넘으면 자동 등록만 멈춘다
)
PHOTO_QUEUE_LIMIT = 20  # 처리를 기다리는 사진 수(원본 바이트가 메모리에 있으므로 상한을 둔다)
_photo_lock = threading.Lock()
_photo_counts: dict[
    tuple[str, str], int
] = {}  # (가족, 날짜) → 오늘 자동으로 읽은 수. 프로세스 메모리라 재시작하면 0 부터
_photo_pending = 0


def _take_daily_slot(group_id: str) -> bool:
    key = (group_id, date.today().isoformat())
    with _photo_lock:
        for old in [k for k in _photo_counts if k[1] != key[1]]:
            del _photo_counts[old]
        if _photo_counts.get(key, 0) >= PHOTO_DAILY_LIMIT:
            return False
        _photo_counts[key] = _photo_counts.get(key, 0) + 1
        return True


def register_chat_photo(
    group_id: str, user_id: str, attachment_id: str, data: bytes, forced: bool = False
) -> None:
    """채팅 사진 하나를 판별해서 문서 사진이면 문서함에 등록한다(읽기 → 민감하지 않으면 저장). 어떤 실패도 던지지 않는다.
    forced 는 사용자가 직접 저장을 눌러 판별과 하루 상한을 건너뛰는 경우다."""
    try:
        with SessionLocal() as db:
            if knowledge_repo.get_by_attachment(db, group_id, attachment_id) is not None:
                return
            if not chat_library.attachment_exists(db, group_id, attachment_id):
                return
        if not forced:
            if photo_judge.judge(data, files.processors.ocr).kind != photo_judge.DOCUMENT:
                return  # 일반 사진·애매한 사진은 자동 등록하지 않는다(애매하면 사용자가 "문서로 저장")
            if not _take_daily_slot(group_id):
                logger.info("chat library photo daily limit reached")
                return
        with SessionLocal() as db:
            photo = service.receive_file(
                db, group_id, user_id, f"{attachment_id}.jpg", "image/jpeg", data
            )
            photo_id = photo.id
        files.process_file(
            photo_id, group_id, user_id, data, f"{attachment_id}.jpg",
            source_attachment_id=attachment_id,
        )  # fmt: skip
    except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        logger.warning("chat library photo register failed error=%s", type(exc).__name__)


def _on_photo(
    group_id: str, user_id: str, attachment_id: str, data: bytes, forced: bool = False
) -> None:
    global _photo_pending
    with _photo_lock:
        if _photo_pending >= PHOTO_QUEUE_LIMIT:
            logger.info("chat library photo queue full")
            return
        _photo_pending += 1

    def run() -> None:
        global _photo_pending
        try:
            register_chat_photo(group_id, user_id, attachment_id, data, forced)
        finally:
            with _photo_lock:
                _photo_pending -= 1

    _submit(run)


def register() -> None:
    """ai_assistant 가 시작할 때 처리 함수를 채팅 쪽 통로에 등록한다."""
    chat_library.register_handlers(_on_document, _on_removed)
    chat_library.register_photo_handler(_on_photo)
