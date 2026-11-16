"""사진 판별 상태 업무 규칙(T05-b0-1). 자동 판별 결과는 shared/chat_library 통로로 받아 적고(ai_assistant 를 직접 부르지 않는다),
사람이 누른 "문서로 저장"은 상태를 `document`(수동)로 맞춘다. 업로더가 일반 사진으로 확인하는 기능은 b0-2 에서 만든다.

규칙(D-13): 자동 판별은 `photo` 를 만들지 못한다. 결과를 못 적거나 줄이 없으면 `pending` 그대로라 타임라인에 나오지 않는다."""

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared import chat_library
from app.shared.db import SessionLocal
from app.shared.errors import ApiError, not_found
from app.shared.rate_limit import FailureLimiter

from . import photo_check_repository as checks
from . import repository as repo
from . import service
from .models import FAMILY
from .schemas import (
    LibraryStateOut,
    PhotoCheckItemOut,
    PhotoCheckOut,
    PhotoChecksOut,
)

logger = logging.getLogger(__name__)

CHECK_LIMIT = 30  # 사용자당 분당 "확인 필요" 조회·확인 요청 수(남용 방지)
CHECK_WINDOW_SECONDS = 60
check_limiter = FailureLimiter()  # 프로세스 메모리(한계는 shared/rate_limit.py 참고)


def _rate(user_id: str) -> None:
    key = f"photocheck:{user_id}"
    wait = check_limiter.retry_after(key, CHECK_LIMIT, CHECK_WINDOW_SECONDS)
    if wait:
        raise ApiError(
            429,
            "too_many_checks",
            "요청이 너무 잦아요. 잠시 후 다시 해 주세요",
            headers={"Retry-After": str(wait)},
        )
    check_limiter.record(key)


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "photo_checks_unavailable",
        "지금은 사진 확인 상태를 불러오지 못해요. 잠시 후 다시 해 주세요",
    )


def review_list(
    db: Session, user: User, group_id: str, limit: int, before: int | None
) -> PhotoChecksOut:
    """내가 올린 사진 중 확인 필요(unsure·failed·15분 넘은 pending)만. 다른 가족 구성원에게는 그 사진의 존재가 보이지 않는다
    (다른 사람이 올린 사진은 이 목록에 들어오지 않는다). 조회가 실패하면 빈 목록이 아니라 503."""
    _rate(user.id)
    try:
        rows, total = checks.list_review(db, group_id, user.id, limit + 1, before)
    except SQLAlchemyError:
        db.rollback()
        raise _unavailable() from None
    page = rows[:limit]
    return PhotoChecksOut(
        items=[
            PhotoCheckItemOut(
                attachment_id=attachment_id,
                thumb_url=f"/family-chat/photos/{attachment_id}?size=thumb",
                created_at=created_at,
                taken_at=taken_at,
                status=status,
            )
            for attachment_id, _message_id, status, created_at, taken_at in page
        ],
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
