"""AI 추억 분석 작업 워커(PR3): 단일 경량 스레드. 새 인프라(Redis·Celery)는 쓰지 않고 PostgreSQL 작업 큐(`family_memory_jobs`)만 쓴다.

- 기본 꺼짐: `FAMILY_MEMORY_ENABLED` 와 `FAMILY_MEMORY_WORKER_ENABLED` 가 둘 다 켜져 있을 때만 서버가 시작할 때 돌린다. 꺼져 있으면 스레드도 없고 작업도 선점하지 않는다.
- 일의 종류마다 `register_handler(kind, run, save)` 로 처리 함수를 등록한다(시작할 때 등록하는 목록). **등록된 종류만 선점**하므로 PR3 만으로는 아무 일도 하지 않는다 —
  이미지 분석 처리 함수는 PR4 가 등록한다. `run(job)` 은 DB 를 쓰지 않고 결과만 돌려주며, 결과는 `save(db, job, result)` 가 `job_service.complete` 의 자격 재확인 뒤에만 저장한다.
- 한 작업은 선점 → 실행 직전 확인 → 실행 → 저장 직전 확인 순서로 가고, 실패는 `job_service.fail`(backoff·상한)이 맡는다. 서버가 재시작돼 멈춘 작업은 임대 만료 뒤 되찾는다.
- 로그에는 결과 종류·예외 종류 이름만 남기고 사진 내용·라벨·경로·OCR 글자를 남기지 않는다."""

import logging
import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.schema import monitor

from . import job_service as js

logger = logging.getLogger(__name__)

Run = Callable[[js.JobView], Any]


@dataclass(frozen=True)
class Handler:
    run: Run
    save: js.SaveResult | None = None


_handlers: dict[str, Handler] = {}  # 종류 → 처리 함수(시작할 때 등록한다)
_thread: threading.Thread | None = None
_stop = threading.Event()


def register_handler(kind: str, run: Run, save: js.SaveResult | None = None) -> None:
    _handlers[kind] = Handler(run, save)


def run_once(worker_id: str) -> str | None:
    """작업 한 건을 끝까지 처리한다. 결과 코드: done | canceled | lost | retry | failed(처리한 것) / None(할 일이 없음).
    어떤 오류도 던지지 않는다(루프가 멈추지 않게): 처리 함수나 저장이 던지면 예외 **종류 이름**만 남기고 재시도 규칙에 맡긴다."""
    kinds = list(_handlers)
    with SessionLocal() as db:
        job = js.claim(db, worker_id, kinds)
    if job is None:
        return None
    handler = _handlers.get(job.kind)
    try:
        with SessionLocal() as db:
            if handler is None or not js.still_allowed(db, job, worker_id):
                return "canceled" if handler is not None else "lost"
        result = handler.run(job)
        with SessionLocal() as db:
            return js.complete(db, job, worker_id, result, handler.save)
    except Exception as exc:  # noqa: BLE001  내용이 로그에 남지 않게 종류만 적는다
        name = type(exc).__name__
        logger.warning("family memory job failed kind=%s error=%s", job.kind, name)
        try:
            with SessionLocal() as db:
                return js.fail(db, job, worker_id, name)
        except Exception as inner:  # noqa: BLE001
            logger.warning("family memory job fail-record failed error=%s", type(inner).__name__)
            return "lost"


def _enabled() -> bool:
    return bool(settings.family_memory_enabled and settings.family_memory_worker_enabled)


def _loop() -> None:
    worker_id = f"w{os.getpid()}-{uuid.uuid4().hex[:6]}"
    while not _stop.is_set():
        did = None
        try:
            if monitor.status().feature_ready("family_memory"):
                did = run_once(worker_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("family memory worker loop error=%s", type(exc).__name__)
        if did is None:
            _stop.wait(max(settings.family_memory_worker_poll_seconds, 0.5))


def start() -> bool:
    """서버가 시작할 때 부른다. 꺼져 있거나 이미 돌고 있으면 아무것도 하지 않는다(False)."""
    global _thread
    if not _enabled() or (_thread is not None and _thread.is_alive()):
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="family-memory-worker", daemon=True)
    _thread.start()
    logger.info("family memory worker started")
    return True


def stop(timeout: float = 5.0) -> None:
    """서버가 끝날 때 부른다. 진행 중인 작업은 임대가 만료되면 되찾는다."""
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout)
        _thread = None
