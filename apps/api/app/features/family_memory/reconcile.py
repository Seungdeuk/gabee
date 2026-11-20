"""파생 데이터 대조 정리(PR6): 동의가 없거나 가족 기능이 꺼진 사람·가족의 파생 데이터(임베딩·추억 후보·끝난/대기 작업)를 **멱등하게** 지운다.

왜 필요한가: 철회·가족 끄기·나가기는 **언제나 먼저 성공**해야 하므로(철회가 파생 데이터 정리 실패에 막히면 안 된다) 즉시 정리 훅은 최선을 다하되 실패해도 철회를 되돌리지 않는다
(`memory_hooks` 의 savepoint). 그 사이 남은 파생 데이터는 자격 판정(`check_photo`/`evaluate`)이 이미 쓰지 못하게 막고 있고(저장 직전 재확인·조회 때 재검증), 이 대조 정리가
뒤늦게라도 모두 지운다 — 워커 루프·후보 새로고침·철회 직후 재시도에서 부른다. 같은 입력으로 여러 번 불려도 결과가 같다. 커밋은 부르는 쪽이 한다."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from . import candidate_repository as cand_repo
from . import job_repository as jobs
from .models import (
    FamilyMemoryJob,
    FamilyMemorySetting,
    MemberMemoryConsent,
    MemoryCandidatePhoto,
    PhotoEmbedding,
)

KIND_EMBEDDING = (
    "photo_embedding"  # analysis.KIND_EMBEDDING 과 같은 값(순환 import 를 피해 여기서 정의한다)
)


@dataclass(frozen=True)
class ReconcileResult:
    embeddings: int = 0
    candidates: int = 0
    done_jobs: int = 0
    canceled_jobs: int = 0

    @property
    def total(self) -> int:
        return self.embeddings + self.candidates + self.done_jobs + self.canceled_jobs


def _no_consent(model):
    """(group_id, user_id) 에 지금 유효한 동의가 없다."""
    return ~exists().where(
        MemberMemoryConsent.group_id == model.group_id,
        MemberMemoryConsent.user_id == model.user_id,
        MemberMemoryConsent.consented_at.is_not(None),
        MemberMemoryConsent.withdrawn_at.is_(None),
    )


def _family_off(model):
    return ~exists().where(
        FamilyMemorySetting.group_id == model.group_id, FamilyMemorySetting.enabled.is_(True)
    )


def reconcile(db: Session, now: datetime | None = None) -> ReconcileResult:
    """동의가 없거나 가족 기능이 꺼진 쪽의 파생 데이터를 지운다(서버 스위치가 꺼져 있다는 이유로는 지우지 않는다: 그건 분석만 멈추는 스위치다)."""
    now = now or datetime.now(UTC)
    emb = (
        db.execute(
            delete(PhotoEmbedding).where(
                or_(_no_consent(PhotoEmbedding), _family_off(PhotoEmbedding))
            )
        ).rowcount
        or 0
    )
    cand_ids = cand_repo.candidate_ids_with_photos(
        db, or_(_no_consent(MemoryCandidatePhoto), _family_off(MemoryCandidatePhoto))
    )
    cand = cand_repo.delete_candidates(db, cand_ids) if cand_ids else 0
    stale = or_(_no_consent(FamilyMemoryJob), _family_off(FamilyMemoryJob))
    canceled = (
        db.execute(
            update(FamilyMemoryJob)
            .where(FamilyMemoryJob.status.in_(jobs.ACTIVE), stale)
            .values(
                status=jobs.CANCELED,
                cancel_reason="reconciled",
                lease_until=None,
                locked_by=None,
                finished_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        or 0
    )
    done = (
        db.execute(
            delete(FamilyMemoryJob).where(
                FamilyMemoryJob.status == jobs.DONE, FamilyMemoryJob.kind == KIND_EMBEDDING, stale
            )
        ).rowcount
        or 0
    )
    return ReconcileResult(emb, cand, done, canceled)


def pending_summary(db: Session) -> dict[str, int]:
    """대조 정리가 지울 것이 남았는지 **읽기만** 해서 센다(운영 점검용: `reconcile_check` 가 쓴다). 모두 0 이면 동의 없음·가족 꺼짐인 쪽에 남은 파생 데이터가 없다는 뜻이다.
    키: embeddings(임베딩 줄), candidate_photos(후보에 든 사진 줄), active_jobs(대기·진행 작업), done_jobs(끝난 임베딩 작업 줄)."""

    def count(model, *conditions) -> int:
        return int(db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)

    return {
        "embeddings": count(
            PhotoEmbedding, or_(_no_consent(PhotoEmbedding), _family_off(PhotoEmbedding))
        ),
        "candidate_photos": count(
            MemoryCandidatePhoto,
            or_(_no_consent(MemoryCandidatePhoto), _family_off(MemoryCandidatePhoto)),
        ),
        "active_jobs": count(
            FamilyMemoryJob,
            FamilyMemoryJob.status.in_(jobs.ACTIVE),
            or_(_no_consent(FamilyMemoryJob), _family_off(FamilyMemoryJob)),
        ),
        "done_jobs": count(
            FamilyMemoryJob,
            FamilyMemoryJob.status == jobs.DONE,
            FamilyMemoryJob.kind == KIND_EMBEDDING,
            or_(_no_consent(FamilyMemoryJob), _family_off(FamilyMemoryJob)),
        ),
    }
