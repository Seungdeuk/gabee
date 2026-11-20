"""사용자 요청형 추억 생성(PR10). 사용자가 "추억 만들기"를 눌렀을 때만 **그 가족의** 자격 있는 사진을 기존 작업 큐에 등록하고, 임베딩이 모두 준비되면 후보를 새로 계산한다.
새 분석·판정 규칙을 만들지 않는다: 자격은 `service.check_group_photos`(E0·D-13, 업로더별 동의·제외·1:1·문서·미확인 사진 제외), 큐는 `job_service.enqueue`(UNIQUE 로 중복 불가),
후보는 `candidate_service.refresh`(멱등)를 그대로 쓴다. 자동 게시·`photo` 승격(E1)은 하지 않는다. 입구 가드(`FAMILY_MEMORY_GENERATE_ENABLED` + 동의 버전 필수)는 T31·출시 승인 전 차단용이다.
요청은 몇 번을 보내도 같은 결과로 수렴한다(이미 등록·완료된 사진은 다시 등록하지 않고, 후보 식별자는 사진 구성으로 정해진다). 로그에는 개수만 남기고 사진·경로·사용자 정보는 남기지 않는다."""

import logging

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.config import settings
from app.shared.errors import ApiError, not_found

from . import analysis, candidate_service, job_service, service
from . import embedding_repository as embeddings
from . import job_repository as jobs
from . import repository as repo
from .schemas import GenerationOut

logger = logging.getLogger(__name__)

MIN_PHOTOS = 3  # 후보가 되려면 필요한 최소 사진 수(grouping min_unique 와 같은 기준)


def _require_open() -> None:
    """입구 가드: 꺼져 있으면 존재를 숨긴다(404). 켜져 있어도 동의 버전 필수가 함께 켜져 있어야 실제 사진을 처리한다."""
    if not settings.family_memory_generate_enabled:
        raise not_found("추억 만들기")
    if not settings.family_memory_consent_version_required:
        raise ApiError(403, "generation_not_open", "추억 만들기는 아직 열려 있지 않아요")


def _status(
    db: Session,
    user: User,
    group_id: str,
    eligible_ids: list[str],
    enqueued: int = 0,
    capped: bool = False,
) -> GenerationOut:
    me = repo.get_consent(db, group_id, user.id)
    embedded = set(embeddings.get_many(db, eligible_ids))
    statuses = jobs.statuses_for(db, eligible_ids, analysis.KIND_EMBEDDING)
    processing = sum(
        1 for a in eligible_ids if a not in embedded and statuses.get(a) in jobs.ACTIVE
    )
    failed = sum(1 for a in eligible_ids if a not in embedded and statuses.get(a) == jobs.FAILED)
    candidates = len(candidate_service.list_for_family(db, group_id))
    if not service._consent_active(me):
        state = "needs_consent"
    elif len(eligible_ids) < MIN_PHOTOS:
        state = "not_enough_photos"
    elif processing > 0:
        state = "processing"
    elif len(embedded) >= MIN_PHOTOS:
        state = "ready"
    elif failed > 0:
        state = "failed"
    else:
        state = "idle"
    return GenerationOut(
        state=state,
        eligible=len(eligible_ids),
        embedded=len(embedded),
        processing=processing,
        failed=failed,
        candidates=candidates,
        enqueued=enqueued,
        capped=capped,
    )


def get_status(db: Session, user: User, group_id: str) -> GenerationOut:
    """현재 생성 진행 상태(읽기 전용, 아무것도 등록·계산하지 않는다)."""
    _require_open()
    _, verdicts = service.check_group_photos(db, group_id, enforce_retro=True)
    eligible = [a for a, v in verdicts.items() if v.eligible]
    return _status(db, user, group_id, eligible)


def request_generation(db: Session, user: User, group_id: str) -> GenerationOut:
    """추억 만들기 요청(멱등). ① 입구·서버·가족·요청자 동의 확인 ② 자격 있는 사진 중 아직 임베딩도 작업도 없는 사진만 큐에 등록(요청당 상한)
    ③ 처리할 작업이 하나도 남지 않았고 임베딩이 있으면 후보를 새로 계산. 처리 중이면 앱이 같은 요청을 다시 보내 진행을 확인한다."""
    _require_open()
    service._require_server_on()
    if not repo.family_enabled(db, group_id):
        raise ApiError(403, "family_off", "가족 AI 추억 기능이 꺼져 있어요")
    if not service._consent_active(repo.get_consent(db, group_id, user.id)):
        raise ApiError(403, "consent_required", "먼저 내 사진 분석에 동의해 주세요")
    _, verdicts = service.check_group_photos(db, group_id, enforce_retro=True)
    eligible = [a for a, v in verdicts.items() if v.eligible]
    embedded = set(embeddings.get_many(db, eligible))
    statuses = jobs.statuses_for(db, eligible, analysis.KIND_EMBEDDING)
    todo = [
        a
        for a in eligible
        if a not in embedded
        and statuses.get(a) in (None, jobs.CANCELED)  # failed 는 다시 돌리지 않는다
    ]
    cap = max(int(settings.family_memory_generate_max_photos), 0)
    if len(eligible) < MIN_PHOTOS:
        todo = []  # 사진이 모자라면 분석하지 않는다(후보가 될 수 없다). 사진이 더 모이면 다시 요청한다
    batch, capped = todo[:cap], len(todo) > cap
    enqueued = 0
    for attachment_id in batch:
        result = job_service.enqueue(db, attachment_id, analysis.KIND_EMBEDDING)
        if result.outcome in ("queued", "requeued"):
            enqueued += 1
    out = _status(db, user, group_id, eligible, enqueued, capped)
    if out.processing == 0 and out.embedded > 0:
        candidate_service.refresh(db, group_id, enforce_retro=True)
        out = _status(db, user, group_id, eligible, enqueued, capped)
    logger.info(
        "family memory generation state=%s eligible=%d enqueued=%d processing=%d",
        out.state,
        out.eligible,
        enqueued,
        out.processing,
    )
    return out
