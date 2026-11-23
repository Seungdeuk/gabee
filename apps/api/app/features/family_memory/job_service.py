"""AI 추억 분석 작업 큐의 업무 규칙(PR3). 이 모듈은 **작업의 등록·선점·완료·복구·차단**만 한다 — 이미지 분석·모델·카드는 없고(PR4 이후)
실제 일은 `worker.register_handler` 로 등록된 함수가 한다.

자격 재확인 4지점(모두 PR1 `service.check_photo` 하나를 쓴다: 서버 스위치·가족 활성화·업로더 동의·사진 제외·확인된 일반 사진·1:1 방 제외):
① 등록(enqueue) ② 선점(claim) ③ 실행 직전(`still_allowed`) ④ 결과 저장 직전(`complete`). 하나라도 자격이 없으면 작업은 `canceled` 로 닫히고 결과는 저장되지 않는다.
철회·가족 나가기·가족 기능 끄기·사진별 제외·사진 삭제는 `memory_hooks` 로 대기·진행 중인 작업을 즉시 막는다(자격 재확인과 별개의 이중 장치).

규칙: 같은 사진·같은 종류는 한 줄(중복 방지). 선점은 `FOR UPDATE SKIP LOCKED` 라 여러 워커가 같은 작업을 가져가지 못하고, 임대(lease)가 만료되면
되찾는다. 시도는 선점할 때마다 늘고 상한(기본 3)을 넘기면 다시 돌리지 않는다(실패는 backoff 뒤 재시도). 자동 재시도로 D-13(자동 photo 금지)을 바꾸지 않는다.
로그·`last_error` 에는 예외 종류 이름·사유 코드만 남기고 사진 내용·라벨·경로·OCR 글자는 남기지 않는다."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared import memory_hooks
from app.shared.config import settings
from app.shared.schema import monitor

from . import job_repository as jobs
from . import repository as repo
from . import service
from .models import FamilyMemoryJob

logger = logging.getLogger(__name__)

KIND_PHOTO = "photo_analysis"
MAX_ATTEMPTS = 3
SKIP_LIMIT = 20  # 한 번 선점하면서 자격이 없어 닫는 작업의 상한(무한 루프 방지)


def _now() -> datetime:
    return datetime.now(UTC)


def lease() -> timedelta:
    return timedelta(seconds=settings.family_memory_job_lease_seconds)


@dataclass(frozen=True)
class JobView:
    """워커가 쓰는 작업 정보(ORM 객체가 아니라 세션이 닫혀도 안전하다). 사진 내용은 없다."""

    id: str
    group_id: str
    attachment_id: str
    user_id: str
    kind: str
    attempts: int
    max_attempts: int


def _view(job: FamilyMemoryJob) -> JobView:
    return JobView(
        job.id,
        job.group_id,
        job.attachment_id,
        job.user_id,
        job.kind,
        job.attempts,
        job.max_attempts,
    )


@dataclass(frozen=True)
class EnqueueResult:
    outcome: str  # queued | requeued | exists | rejected
    reason: str | None = None  # rejected 일 때 자격 사유 코드(service.evaluate 와 같다)
    job_id: str | None = None


# ---------- ① 등록 ----------
def enqueue(
    db: Session, attachment_id: str, kind: str = KIND_PHOTO, now: datetime | None = None
) -> EnqueueResult:
    """사진 한 장의 분석 작업을 등록한다. 자격이 없으면 `rejected`(작업을 만들지 않는다). 같은 사진·종류가 이미 있으면 `exists`(대기·진행·완료·실패),
    자격을 잃어 막았던 작업은 `requeued`(횟수 0부터). 동시에 두 번 불러도 한 줄만 생긴다(UNIQUE)."""
    now = now or _now()
    eligibility = service.check_photo(db, attachment_id)
    ctx = repo.photo_context(db, attachment_id)
    if not eligibility.eligible or ctx is None:
        return EnqueueResult("rejected", eligibility.reason)
    existing = jobs.get_by_attachment(db, attachment_id, kind)
    if existing is None:
        try:
            job = jobs.insert(
                db, ctx.group_id, attachment_id, ctx.uploader_id, kind, MAX_ATTEMPTS, now
            )
            db.commit()
            return EnqueueResult("queued", job_id=job.id)
        except IntegrityError:  # 동시에 다른 요청이 먼저 만들었다
            db.rollback()
            existing = jobs.get_by_attachment(db, attachment_id, kind)
            if existing is None:
                raise
    if existing.status == jobs.CANCELED and jobs.revive(db, existing.id, now):
        db.commit()
        return EnqueueResult("requeued", job_id=existing.id)
    db.rollback()
    return EnqueueResult("exists", job_id=existing.id)


# ---------- ② 선점 ----------
def claim(
    db: Session,
    worker_id: str,
    kinds: list[str],
    now: datetime | None = None,
) -> JobView | None:
    """지금 돌릴 대기 작업 한 건을 선점한다(임대 시작·시도 +1). 먼저 임대가 만료된 작업을 되찾고, 선점하기 전에 자격을 다시 확인해 자격이 없는 작업은
    `canceled` 로 닫고 다음 것을 본다. 대기 작업이 없으면 None."""
    now = now or _now()
    try:
        jobs.recover_expired(db, now)
        db.commit()
        for _ in range(SKIP_LIMIT):
            job = jobs.next_candidate(db, kinds, now)
            if job is None:
                db.commit()
                return None
            eligibility = service.check_photo(db, job.attachment_id)
            if not eligibility.eligible:  # 자격 재확인 ②
                jobs.mark_canceled(job, eligibility.reason, now)
                db.commit()
                continue
            jobs.mark_running(job, worker_id, now, lease())
            db.commit()
            return _view(job)
        return None
    except Exception:
        db.rollback()
        raise


# ---------- ③ 실행 직전 ----------
def still_allowed(db: Session, job: JobView, worker_id: str, now: datetime | None = None) -> bool:
    """실행 직전 확인: 아직 이 워커가 선점하고 있고 자격이 그대로인가. 자격이 없으면 작업을 `canceled` 로 닫는다. False 면 실행하지 않는다."""
    now = now or _now()
    row = jobs.lock_running(db, job.id, worker_id)
    if row is None:
        db.rollback()
        return False  # 취소됐거나 임대가 만료돼 되찾아 갔다
    eligibility = service.check_photo(db, row.attachment_id)
    if not eligibility.eligible:  # 자격 재확인 ③
        jobs.mark_canceled(row, eligibility.reason, now)
        db.commit()
        return False
    db.rollback()  # 잠금만 풀고 상태는 그대로(선점 유지)
    return True


# ---------- ④ 결과 저장·공개 직전 ----------
SaveResult = Callable[[Session, JobView, Any], None]


def complete(
    db: Session,
    job: JobView,
    worker_id: str,
    result: Any = None,
    save: SaveResult | None = None,
    now: datetime | None = None,
) -> str:
    """결과를 저장하고 작업을 끝낸다(`done`). 같은 트랜잭션에서 행을 잠그고 자격을 다시 확인하므로, 그 사이 철회·삭제·제외·가족 끄기가 있었다면
    `save` 를 부르지 않고 작업을 `canceled` 로 닫는다. 결과: done | canceled | lost(이 워커가 더는 선점하지 않음: 되찾아 갔거나 취소됨).
    `save` 가 던지면 그 트랜잭션은 롤백되고(저장된 것 없음) 오류는 그대로 올라간다 — 부르는 쪽이 `fail` 로 재시도를 잡는다."""
    now = now or _now()
    try:
        row = jobs.lock_running(db, job.id, worker_id)
        if row is None:
            db.rollback()
            return "lost"
        eligibility = service.check_photo(db, row.attachment_id)
        if not eligibility.eligible:  # 자격 재확인 ④
            jobs.mark_canceled(row, eligibility.reason, now)
            db.commit()
            return "canceled"
        if save is not None:
            save(db, job, result)
        row.status = jobs.DONE
        row.lease_until = None
        row.locked_by = None
        row.last_error = None
        row.finished_at = row.updated_at = now
        db.commit()
        return "done"
    except Exception:
        db.rollback()
        raise


def fail(db: Session, job: JobView, worker_id: str, error: str, now: datetime | None = None) -> str:
    """실행이 실패했다. 시도 상한 전이면 backoff 뒤 `queued`, 상한이면 `failed`(다시 돌리지 않는다). `error` 는 예외 **종류 이름**만 받는다.
    결과: retry | failed | lost."""
    now = now or _now()
    try:
        row = jobs.lock_running(db, job.id, worker_id)
        if row is None:
            db.rollback()
            return "lost"
        row.last_error = error[:40]
        row.lease_until = None
        row.locked_by = None
        row.updated_at = now
        if row.attempts >= row.max_attempts:
            row.status = jobs.FAILED
            row.finished_at = now
            outcome = "failed"
        else:
            row.status = jobs.QUEUED
            row.run_after = now + jobs.backoff(row.attempts)
            outcome = "retry"
        db.commit()
        return outcome
    except Exception:
        db.rollback()
        raise


# ---------- 다른 기능이 알려 주는 사건: 대기·진행 중인 작업을 즉시 막는다 ----------
def _feature_ready() -> bool:
    return monitor.status().feature_ready("family_memory")


def _on_member_withdrawn(db: Session, group_id: str, user_id: str) -> None:
    """동의 철회·가족 나가기: 그 사람 사진의 대기·진행 작업을 막는다(같은 트랜잭션이라 실패하면 철회·나가기도 취소된다)."""
    if _feature_ready():
        jobs.cancel_for_user(db, group_id, user_id, "withdrawn", _now())


def _on_family_disabled(db: Session, group_id: str) -> None:
    if _feature_ready():
        jobs.cancel_for_group(db, group_id, "family_off", _now())


def _on_photo_excluded(db: Session, group_id: str, attachment_id: str) -> None:
    if _feature_ready():
        jobs.cancel_for_attachment(db, attachment_id, "excluded", _now())


def _on_attachment_removed(db: Session, group_id: str, attachment_id: str) -> None:
    """채팅 사진이 지워졌다: 그 작업 줄도 지운다(진행 중이던 워커는 `complete` 에서 lost 로 끝난다)."""
    if not _feature_ready():
        return
    try:
        jobs.delete_for_attachment(db, attachment_id)
        db.commit()
    except Exception:
        db.rollback()
        raise


memory_hooks.register_member_withdrawn(_on_member_withdrawn)
memory_hooks.register_family_disabled(_on_family_disabled)
memory_hooks.register_photo_excluded(_on_photo_excluded)
memory_hooks.register_attachment_removed(_on_attachment_removed)
