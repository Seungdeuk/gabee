"""AI 추억 분석 작업 큐(`family_memory_jobs`) DB 접근(PR3). 상태를 바꾸는 쓰기는 모두 `WHERE` 조건이 붙은 UPDATE 나 행 잠금 뒤의 변경이라
겹치거나 늦게 온 요청이 다른 워커의 상태를 덮어쓰지 못한다. 커밋은 부르는 쪽이 한다. 사진 내용·라벨·경로는 이 표에 없다."""

from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .models import FamilyMemoryJob

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELED = "canceled"
ACTIVE = (QUEUED, RUNNING)  # 아직 끝나지 않은 작업(자격을 잃으면 막아야 하는 것)

BACKOFF_BASE = timedelta(seconds=30)
BACKOFF_CAP = timedelta(minutes=15)


def backoff(attempts: int) -> timedelta:
    """재시도 대기: 30초, 1분, 2분, … 최대 15분(`attempts` 는 이미 한 시도 수)."""
    return min(BACKOFF_BASE * (2 ** max(attempts - 1, 0)), BACKOFF_CAP)


def get(db: Session, job_id: str) -> FamilyMemoryJob | None:
    return db.get(FamilyMemoryJob, job_id)


def get_by_attachment(db: Session, attachment_id: str, kind: str) -> FamilyMemoryJob | None:
    return db.scalars(
        select(FamilyMemoryJob).where(
            FamilyMemoryJob.attachment_id == attachment_id, FamilyMemoryJob.kind == kind
        )
    ).one_or_none()


def insert(
    db: Session,
    group_id: str,
    attachment_id: str,
    user_id: str,
    kind: str,
    max_attempts: int,
    now: datetime,
) -> FamilyMemoryJob:
    """새 작업 한 줄(같은 사진·종류가 이미 있으면 IntegrityError: 호출한 쪽이 처리한다)."""
    job = FamilyMemoryJob(
        group_id=group_id,
        attachment_id=attachment_id,
        user_id=user_id,
        kind=kind,
        status=QUEUED,
        attempts=0,
        max_attempts=max_attempts,
        run_after=now,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()
    return job


def revive(db: Session, job_id: str, now: datetime) -> bool:
    """자격을 잃어 막았던(`canceled`) 작업을 다시 대기로 돌린다(횟수 0부터). 다른 상태는 건드리지 않는다. 실패(`failed`)는 되살리지 않는다."""
    result = db.execute(
        update(FamilyMemoryJob)
        .where(FamilyMemoryJob.id == job_id, FamilyMemoryJob.status == CANCELED)
        .values(
            status=QUEUED,
            attempts=0,
            run_after=now,
            lease_until=None,
            locked_by=None,
            last_error=None,
            cancel_reason=None,
            finished_at=None,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def next_candidate(db: Session, kinds: list[str], now: datetime) -> FamilyMemoryJob | None:
    """지금 돌릴 수 있는 가장 오래된 대기 작업 한 건을 잠근다(PostgreSQL: `FOR UPDATE SKIP LOCKED` 라 다른 워커가 잠근 줄은 건너뛴다)."""
    if not kinds:
        return None
    return db.scalars(
        select(FamilyMemoryJob)
        .where(
            FamilyMemoryJob.status == QUEUED,
            FamilyMemoryJob.run_after <= now,
            FamilyMemoryJob.kind.in_(kinds),
        )
        .order_by(FamilyMemoryJob.run_after, FamilyMemoryJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()


def mark_running(job: FamilyMemoryJob, worker_id: str, now: datetime, lease: timedelta) -> None:
    job.status = RUNNING
    job.attempts += 1
    job.locked_by = worker_id
    job.lease_until = now + lease
    job.updated_at = now


def mark_canceled(job: FamilyMemoryJob, reason: str, now: datetime) -> None:
    job.status = CANCELED
    job.cancel_reason = reason[:24]
    job.lease_until = None
    job.locked_by = None
    job.finished_at = job.updated_at = now


def lock_running(db: Session, job_id: str, worker_id: str) -> FamilyMemoryJob | None:
    """이 워커가 아직 선점하고 있는 작업만 잠가서 가져온다. 취소됐거나 임대가 만료돼 되찾아 간 작업은 None."""
    return db.scalars(
        select(FamilyMemoryJob)
        .where(
            FamilyMemoryJob.id == job_id,
            FamilyMemoryJob.status == RUNNING,
            FamilyMemoryJob.locked_by == worker_id,
        )
        .with_for_update()
    ).first()


def recover_expired(db: Session, now: datetime) -> int:
    """임대가 만료된 `running` 작업(워커 중단·서버 재시작)을 되찾는다: 시도 상한이면 `failed`, 아니면 backoff 뒤 `queued`. 되찾은 수를 돌려준다."""
    rows = db.scalars(
        select(FamilyMemoryJob)
        .where(FamilyMemoryJob.status == RUNNING, FamilyMemoryJob.lease_until < now)
        .with_for_update(skip_locked=True)
    ).all()
    for job in rows:
        job.lease_until = None
        job.locked_by = None
        job.last_error = "lease_expired"
        job.updated_at = now
        if job.attempts >= job.max_attempts:
            job.status = FAILED
            job.finished_at = now
        else:
            job.status = QUEUED
            job.run_after = now + backoff(job.attempts)
    db.flush()
    return len(rows)


def _cancel_where(db: Session, now: datetime, reason: str, *conditions) -> int:
    result = db.execute(
        update(FamilyMemoryJob)
        .where(FamilyMemoryJob.status.in_(ACTIVE), *conditions)
        .values(
            status=CANCELED,
            cancel_reason=reason[:24],
            lease_until=None,
            locked_by=None,
            finished_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def cancel_for_user(db: Session, group_id: str, user_id: str, reason: str, now: datetime) -> int:
    return _cancel_where(
        db,
        now,
        reason,
        FamilyMemoryJob.group_id == group_id,
        FamilyMemoryJob.user_id == user_id,
    )


def cancel_for_group(db: Session, group_id: str, reason: str, now: datetime) -> int:
    return _cancel_where(db, now, reason, FamilyMemoryJob.group_id == group_id)


def cancel_for_attachment(db: Session, attachment_id: str, reason: str, now: datetime) -> int:
    return _cancel_where(db, now, reason, FamilyMemoryJob.attachment_id == attachment_id)


def delete_for_attachment(db: Session, attachment_id: str) -> None:
    """첨부를 지울 때 그 작업 줄도 지운다(SQLite 는 연쇄 삭제가 없어 코드로도 지운다)."""
    db.execute(delete(FamilyMemoryJob).where(FamilyMemoryJob.attachment_id == attachment_id))


def counts(db: Session, group_id: str | None = None) -> dict[str, int]:
    """상태별 작업 수(운영 점검·시험용). 개인정보는 없다."""
    from sqlalchemy import func

    stmt = select(FamilyMemoryJob.status, func.count()).group_by(FamilyMemoryJob.status)
    if group_id is not None:
        stmt = stmt.where(FamilyMemoryJob.group_id == group_id)
    return {status: int(n) for status, n in db.execute(stmt).all()}
