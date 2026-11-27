"""사진 판별 상태 업무 규칙(T05-b0-1). 자동 판별 결과는 shared/chat_library 통로로 받아 적고(ai_assistant 를 직접 부르지 않는다),
사람이 누른 "문서로 저장"은 상태를 `document`(수동)로 맞춘다. 업로더가 일반 사진으로 확인하는 기능은 b0-2 에서 만든다.

규칙(D-13): 자동 판별은 `photo` 를 만들지 못한다. 결과를 못 적거나 줄이 없으면 `pending` 그대로라 타임라인에 나오지 않는다."""

import logging
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared import chat_library, memory_hooks, photo_analysis_consent
from app.shared.db import SessionLocal
from app.shared.errors import ApiError, not_found
from app.shared.rate_limit import FailureLimiter

from . import photo_check_repository as checks
from . import repository as repo
from . import service, timeline_features, timeline_grouping
from .models import FAMILY
from .schemas import (
    LibraryStateOut,
    PhotoCheckItemOut,
    PhotoCheckOut,
    PhotoChecksOut,
    PhotoExcludeOut,
    TimelineOut,
    TimelinePhotoOut,
)

logger = logging.getLogger(__name__)

CHECK_LIMIT = 30  # 사용자당 분당 "확인 필요" 조회·확인 요청 수(남용 방지)
TIMELINE_LIMIT = (
    60  # 사용자당 분당 타임라인 조회 수(스크롤로 쪽을 이어 받으므로 확인 요청보다 넉넉히)
)
CHECK_WINDOW_SECONDS = 60
check_limiter = FailureLimiter()  # 프로세스 메모리(한계는 shared/rate_limit.py 참고)


def _rate(user_id: str, prefix: str = "photocheck", limit: int | None = None) -> None:
    key = f"{prefix}:{user_id}"
    wait = check_limiter.retry_after(
        key, CHECK_LIMIT if limit is None else limit, CHECK_WINDOW_SECONDS
    )
    if wait:
        raise ApiError(
            429,
            "too_many_checks",
            "요청이 너무 잦아요. 잠시 후 다시 해 주세요",
            headers={"Retry-After": str(wait)},
        )
    check_limiter.record(key)


def failure_kind(status: str, last_error: str | None) -> str | None:
    """`last_error`(예외 종류 이름만 남긴다)를 앱이 쓸 수 있는 원인 코드로 바꾼다. 사진 내용·글자는 다루지 않는다.
    failed → ocr_failed(`OcrFailed`) | timeout(이름에 Timeout) | ai_failed(그 밖의 종류). 오래 pending 이면 stalled. 그 밖의 상태는 None."""
    if status == checks.FAILED:
        if last_error == "OcrFailed":
            return "ocr_failed"
        if last_error and "timeout" in last_error.lower():
            return "timeout"
        return "ai_failed"
    if status == checks.PENDING:
        return "stalled"
    return None


def claim_recheck(db: Session, user: User, group_id: str, attachment_id: str) -> tuple[str, int]:
    """재검사 요청의 권한·상태 검사와 맡기기(판별을 실제로 돌리는 것은 `photo_service.recheck_photo`). 업로더 본인·가족 전체방·살아 있는 사진만
    (아니면 404: 존재를 숨긴다). (결과, 남은 횟수): `claimed` | `in_progress`. 실패·지연이 아니면 409 `recheck_not_needed`, 횟수를 다 썼으면
    409 `recheck_limit_reached`. 어떤 경우에도 사진을 `photo` 로 바꾸지 않는다(D-13)."""
    _rate(user.id)
    try:
        ctx = checks.uploader_context(db, group_id, attachment_id)
        if ctx is None:
            raise not_found("사진")
        uploader_id, room_kind, alive = ctx
        if uploader_id != user.id or room_kind != FAMILY or not alive:
            raise not_found("사진")
        outcome = checks.claim_recheck(db, group_id, attachment_id, user.id)
        left = max(
            checks.RECHECK_MAX - checks.recheck_counts(db, [attachment_id]).get(attachment_id, 0), 0
        )
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    if outcome in ("claimed", "in_progress"):
        return outcome, left
    if outcome == "not_needed":
        raise ApiError(
            409,
            "recheck_not_needed",
            "다시 확인할 필요가 없는 사진이에요(실패·처리 지연만 가능해요)",
        )
    if outcome == "limit":
        raise ApiError(
            409,
            "recheck_limit_reached",
            "다시 확인할 수 있는 횟수를 넘었어요. 문서로 저장하거나 일반 사진으로 직접 확인해 주세요",
        )
    raise not_found("사진")


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "photo_checks_unavailable",
        "지금은 사진 확인 상태를 불러오지 못해요. 잠시 후 다시 해 주세요",
    )


def review_list(
    db: Session,
    user: User,
    group_id: str,
    limit: int,
    before: int | None,
    excluded: bool = False,
) -> PhotoChecksOut:
    """내가 올린 사진 중 확인 필요(unsure·failed·15분 넘은 pending)만(`excluded=True` 면 내가 타임라인에서 뺀 사진만). 다른 가족
    구성원에게는 그 사진의 존재가 보이지 않는다(다른 사람이 올린 사진은 이 목록에 들어오지 않는다). 조회가 실패하면 빈 목록이 아니라 503."""
    _rate(user.id)
    try:
        rows, total = checks.list_review(
            db, group_id, user.id, limit + 1, before, excluded=excluded
        )
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    page = rows[:limit]
    try:
        details = checks.review_details(db, group_id, [r[0] for r in page])
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    items = []
    for attachment_id, _message_id, status, created_at, taken_at in page:
        last_error, used = details.get(attachment_id, (None, 0))
        left = max(checks.RECHECK_MAX - used, 0)
        items.append(
            PhotoCheckItemOut(
                attachment_id=attachment_id,
                thumb_url=f"/family-chat/photos/{attachment_id}?size=thumb",
                created_at=created_at,
                taken_at=taken_at,
                status="excluded"
                if excluded
                else status,  # 문서 줄에서 뺀 사진은 줄 상태가 document 라도 "뺀 사진"으로 보인다
                failure_kind=failure_kind(status, last_error),
                can_retry=status in (checks.FAILED, checks.PENDING) and left > 0,
                retries_left=left if status in (checks.FAILED, checks.PENDING) else 0,
            )
        )
    return PhotoChecksOut(
        items=items,
        needs_review_count=total,
        next_before=page[-1][1] if len(rows) > limit else None,
    )


def confirm_general(db: Session, user: User, group_id: str, attachment_id: str) -> PhotoCheckOut:
    """업로더가 명시적으로 일반 사진으로 확인(D-13). 업로더 본인·가족 전체방·살아 있는 사진만(아니면 404: 존재를 숨긴다).
    문서(자동·수동 모두)이거나 문서함에 등록된 사진은 409 `document_to_photo_blocked`(D-15·D-16: MVP 는 document→photo 차단),
    문서함 등록 여부를 확인하지 못하면 503(막는 쪽), 올린 지 15분 안 된 pending 은 409 `check_in_progress`."""
    _rate(user.id)
    try:
        ctx = checks.uploader_context(db, group_id, attachment_id)
        if ctx is None:
            raise not_found("사진")
        uploader_id, room_kind, alive = ctx
        if uploader_id != user.id or room_kind != FAMILY or not alive:
            raise not_found("사진")
        registered = chat_library.registered_state(db, group_id, attachment_id)
        if registered is None:
            raise _unavailable()
        if registered:
            raise ApiError(
                409,
                "document_to_photo_blocked",
                "문서함에 저장된 사진은 일반 사진으로 바꿀 수 없어요",
            )
        outcome = checks.confirm_general(db, group_id, attachment_id, user.id)
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    if outcome in ("confirmed", "already"):
        return PhotoCheckOut(status="photo", source="manual")
    if outcome == "document":
        raise ApiError(
            409, "document_to_photo_blocked", "문서로 저장된 사진은 일반 사진으로 바꿀 수 없어요"
        )
    if outcome == "in_progress":
        raise ApiError(
            409, "check_in_progress", "사진을 확인하는 중이에요. 잠시 후에 다시 해 주세요"
        )
    raise not_found(
        "사진"
    )  # missing: 판별 줄이 없는 예전 사진은 확인 대상이 아니다(타임라인에도 나오지 않는다)


def exclude_from_timeline(
    db: Session, user: User, group_id: str, attachment_id: str
) -> PhotoExcludeOut:
    """업로더가 자기 사진을 가족 타임라인에서 뺀다(결정 1: 올린 사람만). 채팅 원본은 그대로 남고 타임라인에서만 숨는다.
    업로더 본인·가족 전체방·살아 있는 사진만(아니면 404: 존재를 숨긴다). 타임라인에 있는(`photo`) 사진만 뺄 수 있고 아니면 409
    `not_in_timeline`. 이미 뺐으면 같은 200(이력은 한 줄). 다시 넣는 것은 일반 사진 확인(안내 확인란 포함)이다."""
    _rate(user.id)
    try:
        ctx = checks.uploader_context(db, group_id, attachment_id)
        if ctx is None:
            raise not_found("사진")
        uploader_id, room_kind, alive = ctx
        if uploader_id != user.id or room_kind != FAMILY or not alive:
            raise not_found("사진")
        row = checks.get(db, group_id, attachment_id)
        choice = checks.timeline_choices(db, group_id).get(attachment_id)
        auto_row = row is not None and row.source == checks.AUTO
        # 자동 판별 줄(문서·대기·애매·실패)은 어떤 경우에도 판정 줄을 덮지 않고 이력 줄로만 선택을 적는다
        auto_judged = auto_row and row.status in (
            checks.DOCUMENT,
            checks.PENDING,
            checks.UNSURE,
            checks.FAILED,
        )
        if row is not None and (row.status == checks.DOCUMENT or choice is not None or auto_judged):
            # 문서 줄·자동 판별 줄(애매·대기·실패)·이미 수동 선택을 쓰는 사진: 판별 상태 줄(문서함 판정)은 건드리지 않고 타임라인 선택(이력 줄)만 적는다
            # (자동 판별 줄을 excluded 로 덮으면 뒤늦게 끝난 판별·문서함 등록과 어긋난다)
            if choice == checks.TIMELINE_EXCLUDE:
                return PhotoExcludeOut(status="excluded", source="manual")
            shown = choice == checks.TIMELINE_INCLUDE
            if not shown and auto_judged and row.status in checks.AUTO_CANDIDATE_STATUSES:
                # 자동 후보(애매)는 분석을 통과해 타임라인에 보일 때만 뺄 수 있다(보이지 않는 사진은 뺄 것이 없다). 문서·대기·실패 줄은 자동 후보가 아니다
                shown = _auto_visible(db, group_id, attachment_id)
            if not shown:
                raise ApiError(409, "not_in_timeline", "타임라인에 있는 사진만 뺄 수 있어요")
            checks.set_timeline_choice(
                db, group_id, attachment_id, user.id, checks.TIMELINE_EXCLUDE
            )
            return PhotoExcludeOut(status="excluded", source="manual")
        outcome = checks.exclude_photo(db, group_id, attachment_id, user.id)
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    if outcome in ("excluded", "already"):
        return PhotoExcludeOut(status="excluded", source="manual")
    if outcome == "not_in_timeline":
        raise ApiError(409, "not_in_timeline", "타임라인에 있는 사진만 뺄 수 있어요")
    raise not_found("사진")


def include_in_timeline(
    db: Session, user: User, group_id: str, attachment_id: str
) -> PhotoCheckOut:
    """업로더가 자기 사진을 가족 타임라인에 (다시) 넣는다. **타임라인 표시에만 영향**: 문서함 판정(`chat_photo_checks` 의 document 등)과 문서함
    내용은 바뀌지 않는다(`/check` 의 document→photo 차단은 그대로). 문서 줄·문서함에 등록된 사진·이미 수동 선택을 쓰는 사진은 이력 줄로만
    선택을 적고, 그 밖의 줄(애매·실패·뺀 사진 등)은 기존 일반 사진 확인(`confirm_general`)과 같다. 업로더 본인·가족 전체방·살아 있는 사진만
    (아니면 404: 존재를 숨긴다). 같은 요청을 다시 보내도 200. 응답의 status 는 "타임라인에서 보이는 사진"이라는 뜻이다."""
    _rate(user.id)
    try:
        ctx = checks.uploader_context(db, group_id, attachment_id)
        if ctx is None:
            raise not_found("사진")
        uploader_id, room_kind, alive = ctx
        if uploader_id != user.id or room_kind != FAMILY or not alive:
            raise not_found("사진")
        row = checks.get(db, group_id, attachment_id)
        if row is None:
            raise not_found("사진")
        choice = checks.timeline_choices(db, group_id).get(attachment_id)
        registered = chat_library.registered_state(db, group_id, attachment_id)
        # 문서함 등록 여부를 못 읽어도(None) 줄을 바꾸지 않는 선택 기록 쪽으로 간다(안전한 쪽)
        if row.status == checks.DOCUMENT or registered is not False or choice is not None:
            checks.set_timeline_choice(
                db, group_id, attachment_id, user.id, checks.TIMELINE_INCLUDE
            )
            return PhotoCheckOut(status="photo", source="manual")
        outcome = checks.confirm_general(db, group_id, attachment_id, user.id)
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    return _confirm_response(outcome)


def _confirm_response(outcome: str) -> PhotoCheckOut:
    if outcome in ("confirmed", "already"):
        return PhotoCheckOut(status="photo", source="manual")
    if outcome == "document":
        raise ApiError(
            409, "document_to_photo_blocked", "문서로 저장된 사진은 일반 사진으로 바꿀 수 없어요"
        )
    if outcome == "in_progress":
        raise ApiError(
            409, "check_in_progress", "사진을 확인하는 중이에요. 잠시 후에 다시 해 주세요"
        )
    raise not_found("사진")


def _analysis_allowed(db: Session, group_id: str, attachment_ids: list[str]) -> set[str]:
    """타임라인 이미지 분석(자동 후보·유사 묶기)을 해도 되는 사진만: 서버 스위치 `TIMELINE_AUTO_CANDIDATES` 가 켜져 있고(기본 꺼짐)
    ADR 0020 의 3중 조건(FAMILY_MEMORY_ENABLED·가족 활성화·업로더 동의)과 사진별 분석 제외를 만족한 것(ADR 0026). 확인할 수 없으면 빈 집합."""
    if not timeline_features.enabled() or not attachment_ids:
        return set()
    return photo_analysis_consent.allowed_photos(
        db, group_id, checks.uploaders_for(db, group_id, attachment_ids)
    )


def _auto_visible(db: Session, group_id: str, attachment_id: str) -> bool:
    """업로더 확인 없이 자동 후보로 타임라인에 보이는 사진인가(분석이 허용됐고 문서 후보가 아님)."""
    if attachment_id not in _analysis_allowed(db, group_id, [attachment_id]):
        return False
    found = timeline_features.load(attachment_id)
    return found is not None and found.is_candidate


def schedule_after_upload(db: Session, group_id: str, uploader_id: str, attachment_id: str) -> None:
    """업로드 직후 타임라인 분석을 뒤에서 맡긴다: 스위치와 ADR 0020 조건을 만족하고, 판별이 이미 끝나 분석 범위(photo·자동 unsure)에 든 사진만.
    방금 올린 사진은 보통 판별 대기(pending)라 맡기지 않는다(판별이 끝난 뒤 타임라인 조회 때 맡긴다, ADR 0026 분석 범위). 실패해도 던지지 않는다."""
    try:
        if (
            timeline_features.enabled()
            and _in_analysis_scope(db, group_id, attachment_id)
            and _analysis_allowed(db, group_id, [attachment_id])
        ):
            timeline_features.schedule([attachment_id])
    except Exception as exc:  # noqa: BLE001  업로드를 깨지 않는다
        logger.warning("timeline schedule skipped error=%s", type(exc).__name__)


def _still_allowed(attachment_id: str) -> bool:
    """분석 작업이 결과를 쓰기 직전에 부른다: 지금도 스위치가 켜져 있고 ADR 0020 조건을 만족하는가(새 세션으로 다시 읽는다)."""
    with SessionLocal() as db:
        group_id = checks.attachment_group(db, attachment_id)
        if group_id is None:
            return False  # 첨부가 지워졌다
        if not _in_analysis_scope(db, group_id, attachment_id):
            return False  # 그 사이 문서·실패·뺀 사진이 됐다(분석 범위 밖)
        return attachment_id in _analysis_allowed(db, group_id, [attachment_id])


def _in_analysis_scope(db: Session, group_id: str, attachment_id: str) -> bool:
    """ADR 0026 분석 범위: 업로더가 확인한 photo, 자동 판별 unsure, 업로더가 타임라인에 직접 넣은 사진. 문서·대기·실패·뺀 사진은 아니다."""
    choice = checks.timeline_choices(db, group_id).get(attachment_id)
    if choice == checks.TIMELINE_EXCLUDE:
        return False
    if choice == checks.TIMELINE_INCLUDE:
        return True  # 업로더의 명시적 포함(같은 날 묶기용 분석만 쓰인다)
    row = checks.get(db, group_id, attachment_id)
    return row is not None and (
        row.status == checks.PHOTO
        or (row.status in checks.AUTO_CANDIDATE_STATUSES and row.source == checks.AUTO)
    )


def _encode_cursor(display_at: datetime, message_id: int) -> str:
    return f"{_utc(display_at).isoformat()}_{message_id}"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _decode_cursor(before: str) -> tuple[datetime, int]:
    try:
        stamp, _, raw_id = before.rpartition("_")
        message_id = int(raw_id)
        return _utc(datetime.fromisoformat(stamp)), message_id
    except ValueError:
        raise ApiError(422, "invalid_cursor", "다음 쪽을 불러올 수 없어요") from None


def _plain_timeline(rows: list, limit: int, user: User) -> TimelineOut:
    """이미지 분석 없이(스위치 꺼짐) DB 순서·커서 그대로 쪽을 만든다. 같은 업로드 묶음은 batch_id 로 앱이 한 카드로 묶는다."""
    page = rows[:limit]
    return TimelineOut(
        items=[
            TimelinePhotoOut(
                attachment_id=att_id,
                message_id=message_id,
                thumb_url=f"/family-chat/photos/{att_id}?size=thumb",
                display_at=display_at,
                taken_at=taken_at,
                created_at=created_at,
                batch_id=batch_id,
                mine=uploader_id == user.id,
                group_kind="batch" if batch_id else "single",
                confirmed=True,
            )
            for att_id, message_id, display_at, taken_at, created_at, batch_id, uploader_id in page
        ],
        next_before=(_encode_cursor(page[-1][2], page[-1][1]) if len(rows) > limit else None),
        analyzing=0,
        analysis_failed=0,
    )


def timeline(db: Session, user: User, group_id: str, limit: int, before: str | None) -> TimelineOut:
    """가족 타임라인: 일반 사진으로 확인된 가족 전체방 사진만 촬영일(없으면 보낸 시각) 최신순. 판별 결과를 읽지 못하면 빈 목록이
    아니라 503(fail-closed). 가족 그룹은 로그인한 사용자의 멤버십으로만 정해진다."""
    _rate(user.id, "timeline", TIMELINE_LIMIT)
    cursor = _decode_cursor(before) if before else None
    try:
        choices = checks.timeline_choices(
            db, group_id
        )  # 업로더의 명시적 포함·제외(문서함 판정과 별개, 모델 결과보다 우선)
        include_ids = {a for a, c in choices.items() if c == checks.TIMELINE_INCLUDE}
        exclude_ids = {a for a, c in choices.items() if c == checks.TIMELINE_EXCLUDE}
        if not timeline_features.enabled():
            # 스위치 꺼짐(기본, ADR 0026): 이미지 분석·자동 후보·유사 묶기가 없으므로 DB 커서로 바로 쪽을 나눈다(오래된 사진까지 끝까지 넘겨 본다)
            rows = checks.list_timeline(
                db, group_id, limit + 1, cursor, None, include_ids, exclude_ids
            )
            return _plain_timeline(rows, limit, user)
        # 스위치 켜짐(운영 승인 사항, ADR 0026): 자동 후보는 판별이 끝난 애매(unsure) 줄만 분석한다. 문서(document)·대기(pending)·실패(failed)·뺀 줄은
        # 자동 분석하지 않는다(문서 줄은 업로더가 직접 넣어야 보인다). 분석 허용이 자동 공개의 안전성을 뜻하지는 않는다.
        auto_ids = [
            a
            for a in checks.list_auto_candidate_ids(db, group_id, timeline_features.WINDOW_CAP)
            if a not in choices
        ]
        allowed = _analysis_allowed(db, group_id, auto_ids)  # ADR 0020 조건
        auto_ids = [a for a in auto_ids if a in allowed]
        # 분석 결과(캐시)만 읽는다. 분석 전·실패 사진은 자동 후보가 아니고, 분석은 뒤에서 한 번에 몇 장씩만 맡긴다(요청은 기다리지 않는다)
        state = timeline_features.classify_candidates(auto_ids)
        rows = checks.list_timeline(
            db,
            group_id,
            timeline_features.WINDOW_CAP,
            None,
            set(state.eligible),
            include_ids,
            exclude_ids,
        )
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    # 같은 날 비슷한 사진·같은 업로드 묶음을 한 묶음으로(묶음은 가장 이른 시각 자리에 모인다), 쪽 나누기는 묶은 뒤에 한다
    # 유사 사진 묶기의 임베딩도 분석이 허용된 사진 것만 쓴다(스위치 꺼짐·동의 없음이면 같은 업로드 묶음으로만 묶인다)
    try:
        embed_ok = _analysis_allowed(db, group_id, [row[0] for row in rows])
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    confirmed_embeddings = {
        row[0]: (timeline_features.load(row[0]) if row[0] in embed_ok else None) for row in rows
    }
    # 직접 확인·포함한 사진은 자동 후보 목록에 없어 분석이 맡겨지지 않는다: 허용된 사진 중 분석 결과·실패 기록이 없는 것은 묶기용으로 조용히 맡긴다
    # (정리 중 숫자에는 세지 않는다. 분석이 끝나면 다음 조회부터 같은 날 비슷한 사진과 묶인다)
    missing = [
        a
        for a in embed_ok
        if confirmed_embeddings.get(a) is None and timeline_features.failure(a) is None
    ]
    if missing:  # 자동 후보 분석과 대기열을 나눠 쓰도록 조회당 절반만
        timeline_features.schedule(missing[: timeline_features.BACKFILL_PER_REQUEST // 2])
    group_inputs = [
        timeline_grouping.GroupItem(
            attachment_id=row[0],
            display_at=_utc(row[2]),
            batch_id=row[5],
            embedding=(
                confirmed_embeddings[row[0]].embedding if confirmed_embeddings[row[0]] else None
            ),
        )
        for row in rows
    ]
    # 같은 사진(같은 날, 임베딩 유사도 0.99 이상)은 하나만 보인다: 직접 확인·포함한 사진을 먼저 남긴다. 뺀 사진은 응답에서만 빠지고 채팅·문서함·DB 는 그대로다.
    # 이미 타임라인에서 뺀 사진은 위에서 걸러졌으므로, 남긴 사진을 업로더가 빼면 다음 조회부터 숨겨졌던 중복 사진이 나타난다.
    hidden = timeline_grouping.duplicate_ids(
        group_inputs,
        preferred={row[0] for row in rows if row[0] in include_ids or row[0] not in state.eligible},
    )
    if hidden:
        rows = [row for row in rows if row[0] not in hidden]
        group_inputs = [item for item in group_inputs if item.attachment_id not in hidden]
    assigns = timeline_grouping.group_items(group_inputs)
    ordered = sorted(
        rows,
        key=lambda row: (assigns[row[0]].display_at, row[1]),
        reverse=True,
    )
    if cursor is not None:
        c_at, c_id = cursor
        ordered = [row for row in ordered if (assigns[row[0]].display_at, row[1]) < (c_at, c_id)]
    page = ordered[:limit]
    return TimelineOut(
        items=[
            TimelinePhotoOut(
                attachment_id=att_id,
                message_id=message_id,
                thumb_url=f"/family-chat/photos/{att_id}?size=thumb",
                display_at=assigns[att_id].display_at,
                taken_at=taken_at,
                created_at=created_at,
                batch_id=assigns[att_id].key,
                mine=uploader_id == user.id,
                group_kind=assigns[att_id].kind,
                confirmed=att_id in include_ids or att_id not in state.eligible,
            )
            for att_id, message_id, _display_at, taken_at, created_at, _batch_id, uploader_id in page
        ],
        next_before=(
            _encode_cursor(assigns[page[-1][0]].display_at, page[-1][1])
            if len(ordered) > limit
            else None
        ),
        analyzing=state.analyzing,
        analysis_failed=state.failed,
    )


def library_state(db: Session, user: User, group_id: str, attachment_id: str) -> LibraryStateOut:
    """가족 전체방 사진의 문서함 등록 여부(방에 들어갈 수 있는 가족 누구나). 확인하지 못하면 not_registered(성공으로 표시하지 않는다)."""
    attachment = repo.get_attachment(db, attachment_id)
    if attachment is None or attachment.group_id != group_id:
        raise not_found("사진")
    room = service.resolve_room(db, user, group_id, attachment.room_id)
    if room.kind != FAMILY:
        raise ApiError(
            409, "not_family_room", "가족 전체방에 올린 사진만 문서함을 확인할 수 있어요"
        )
    registered = chat_library.registered_state(db, group_id, attachment_id)
    return LibraryStateOut(state="registered" if registered else "not_registered")


def remove_from_library(db: Session, user: User, group_id: str, attachment_id: str) -> None:
    """가족 전체방 사진에서 만든 문서함 기록을 뺀다(T09). 권한은 등록 여부 조회와 같다(방에 들어갈 수 있는 가족 누구나, 문서함 기록 삭제
    `DELETE /ai-assistant/knowledge/items/{id}` 와 같은 범위). 채팅 사진·메시지는 그대로 두고 문서함 기록·검색 조각·문서함 원본 사본만 지운다.
    없는 사진·다른 가족은 404, 1:1 방은 409, 문서함에 없으면 409 `not_in_library`, 등록 여부를 확인하지 못하거나 지우지 못하면 503."""
    attachment = repo.get_attachment(db, attachment_id)
    if attachment is None or attachment.group_id != group_id:
        raise not_found("사진")
    room = service.resolve_room(db, user, group_id, attachment.room_id)
    if room.kind != FAMILY:
        raise ApiError(409, "not_family_room", "가족 전체방에 올린 사진만 문서함에서 뺄 수 있어요")
    registered = chat_library.registered_state(db, group_id, attachment_id)
    if registered is None:
        raise ApiError(
            503,
            "library_unavailable",
            "지금은 문서함을 확인할 수 없어요. 잠시 뒤 다시 시도해 주세요",
        )
    if not registered:
        raise ApiError(409, "not_in_library", "문서함에 없는 사진이에요")
    try:
        chat_library.remove_from_library(db, group_id, attachment_id)
    except Exception as exc:  # noqa: BLE001  뺀 것처럼 보이지 않게 503 으로 알린다(종류만 기록)
        db.rollback()
        logger.warning("library remove failed error=%s", type(exc).__name__)
        raise ApiError(
            503, "library_unavailable", "문서함에서 빼지 못했어요. 잠시 뒤 다시 시도해 주세요"
        ) from exc


def record_auto_result(group_id: str, attachment_id: str, status: str, error: str | None) -> bool:
    """자동 판별 결과를 적는다(판별 스레드에서 부르므로 자기 세션을 연다). 이미 정해진 줄은 바꾸지 않는다.
    돌려주는 값: 문서함에 등록해도 되는가. 업로더가 이미 `photo` 로 확인한 줄이면 False(자동 결과는 그 확인을 바꾸지 못하므로
    문서함 등록도 하지 않는다)."""
    with SessionLocal() as db:
        checks.record_auto(db, group_id, attachment_id, status, error)
        row = checks.get(db, group_id, attachment_id)
        return not (row is not None and row.status == checks.PHOTO)


def mark_document(
    db: Session, group_id: str, attachment_id: str, actor_user_id: str | None = None
) -> None:
    """사람이 "문서로 저장"을 눌렀을 때 상태를 문서(수동)로 맞춘다(바뀌면 이력 한 줄). 실패하면 던진다(상태가 `photo` 로 남은 채 저장되지 않게)."""
    checks.mark_document_manual(db, group_id, attachment_id, actor_user_id)


chat_library.register_check_recorder(record_auto_result)


# ---------- ADR 0020: 동의 철회·가족 비활성화·사진 분석 제외 때 타임라인 분석 결과(임베딩)를 지운다 ----------
def _forget_uploader_analysis(db: Session, group_id: str, user_id: str) -> None:
    for attachment_id in checks.image_attachment_ids(db, group_id, user_id):
        timeline_features.forget(attachment_id)


def _forget_family_analysis(db: Session, group_id: str) -> None:
    for attachment_id in checks.image_attachment_ids(db, group_id):
        timeline_features.forget(attachment_id)


def _forget_photo_analysis(db: Session, group_id: str, attachment_id: str) -> None:
    timeline_features.forget(attachment_id)


memory_hooks.register_member_withdrawn(_forget_uploader_analysis)
memory_hooks.register_family_disabled(_forget_family_analysis)
memory_hooks.register_photo_excluded(_forget_photo_analysis)
timeline_features.set_write_guard(
    _still_allowed
)  # 대기 중이던 분석이 자격을 잃은 뒤 결과를 쓰지 않게
