"""사진 판별 상태(`chat_photo_checks`) DB 접근. 모든 쓰기는 조건부 UPDATE 하나로 끝내 늦게 오거나 겹쳐 온 결과가 상태를 덮어쓰지 못하게 한다."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    FAMILY,
    ChatPhotoCheck,
    ChatPhotoCheckEvent,
    ChatRoom,
    Message,
    MessageAttachment,
)

# 이력 이유 코드(자유 글 없음). 새 이유는 여기에만 추가한다.
REASON_UPLOADER_CONFIRMED = "uploader_confirmed_general"
REASON_FAMILY_DOCUMENT = "family_saved_as_document"
REASON_UPLOADER_REMOVED = "uploader_removed"
# 업로드 뒤 이 시간이 지난 pending 은 "처리 지연"으로 업로더에게 보인다(초기값, b0-3 재시도 구현 뒤 재조정). 자동 판별 실패·일반 사진 확정 기준이 아니다.
STALE_PENDING = timedelta(minutes=15)

PENDING = "pending"
PHOTO = "photo"
DOCUMENT = "document"
UNSURE = "unsure"
FAILED = "failed"
EXCLUDED = "excluded"  # 업로더가 타임라인에서 뺀 사진(수동). 확인 필요 목록에는 다시 뜨지 않고, 업로더가 다시 넣을 수 있다
STATUSES = frozenset({PENDING, PHOTO, DOCUMENT, UNSURE, FAILED, EXCLUDED})
AUTO = "auto"
MANUAL = "manual"
# 자동 판별이 쓸 수 있는 결과. PHOTO 는 없다: OCR·실험 모델의 판정만으로 일반 사진을 확정하지 않는다(D-13, 업로더 확인은 b0-2).
AUTO_RESULTS = frozenset({DOCUMENT, UNSURE, FAILED})


def new_pending(attachment_id: str, group_id: str) -> ChatPhotoCheck:
    """업로드 트랜잭션에 함께 넣을 `pending` 줄(저장은 부르는 쪽 트랜잭션이 한다)."""
    return ChatPhotoCheck(
        attachment_id=attachment_id, group_id=group_id, status=PENDING, source=AUTO
    )


def get(db: Session, group_id: str, attachment_id: str) -> ChatPhotoCheck | None:
    return db.scalars(
        select(ChatPhotoCheck).where(
            ChatPhotoCheck.attachment_id == attachment_id, ChatPhotoCheck.group_id == group_id
        )
    ).one_or_none()


def record_auto(
    db: Session, group_id: str, attachment_id: str, status: str, error: str | None = None
) -> bool:
    """자동 판별 결과를 적는다. 자동 줄만, 그리고 아직 `pending` 일 때만 바꾼다(이미 정해졌거나 사람이 정했거나 지워졌으면 아무것도
    하지 않고 False). 같은 결과가 두 번 와도 늦게 와도 처음 한 번만 적힌다. 단 `document` 는 숨기는 방향이라 `unsure`·`failed`
    (자동)에서도 올라간다(늦게 온 문서 판정이 문서함 등록과 어긋나지 않게). `photo` 와 모르는 상태는 거부한다."""
    if status not in AUTO_RESULTS:
        raise ValueError("auto result must be one of document|unsure|failed")
    from_states = (PENDING, UNSURE, FAILED) if status == DOCUMENT else (PENDING,)
    result = db.execute(
        update(ChatPhotoCheck)
        .where(
            ChatPhotoCheck.attachment_id == attachment_id,
            ChatPhotoCheck.group_id == group_id,
            ChatPhotoCheck.status.in_(from_states),
            ChatPhotoCheck.source == AUTO,
        )
        .values(
            status=status,
            last_error=error[:40] if error else None,
            checked_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


def _add_event(
    db: Session,
    group_id: str,
    attachment_id: str,
    actor_user_id: str | None,
    from_status: str | None,
    to_status: str,
    reason: str,
    now: datetime,
) -> None:
    """이력 한 줄(커밋은 부르는 쪽). 상태를 바꾸는 UPDATE 와 같은 트랜잭션에서만 부른다."""
    db.add(
        ChatPhotoCheckEvent(
            attachment_id=attachment_id,
            group_id=group_id,
            actor_user_id=actor_user_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            created_at=now,
        )
    )


def mark_document_manual(
    db: Session, group_id: str, attachment_id: str, actor_user_id: str | None = None
) -> None:
    """사람이 "문서로 저장"을 눌렀다(D-15: 가족 누구나). 어떤 상태든 `document`(수동)로 맞춘다. 줄이 없는 예전 사진은 새로 만든다.
    문서로 숨기는 방향이라 안전하다. 이후 자동 판별은 이 줄을 바꾸지 못한다. 상태나 출처가 실제로 바뀔 때만 이력을 한 줄 남긴다
    (이미 수동 문서면 아무것도 쓰지 않는다: 같은 요청이 두 번 와도 이력은 한 줄). 이전 상태는 행 잠금(PostgreSQL)과 조건부 UPDATE 로 정확히 적는다."""
    now = datetime.now(UTC)
    for _ in range(3):
        prior = db.execute(
            select(ChatPhotoCheck.status, ChatPhotoCheck.source)
            .where(
                ChatPhotoCheck.attachment_id == attachment_id, ChatPhotoCheck.group_id == group_id
            )
            .with_for_update()
        ).first()
        if prior is not None:
            if (prior.status, prior.source) == (DOCUMENT, MANUAL):
                db.commit()
                return
            result = db.execute(
                update(ChatPhotoCheck)
                .where(
                    ChatPhotoCheck.attachment_id == attachment_id,
                    ChatPhotoCheck.group_id == group_id,
                    ChatPhotoCheck.status == prior.status,
                    ChatPhotoCheck.source == prior.source,
                )
                .values(status=DOCUMENT, source=MANUAL, last_error=None, checked_at=now)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount == 1:
                _add_event(
                    db,
                    group_id,
                    attachment_id,
                    actor_user_id,
                    prior.status,
                    DOCUMENT,
                    REASON_FAMILY_DOCUMENT,
                    now,
                )
                db.commit()
                return
            db.rollback()  # 읽은 뒤 다른 요청이 바꿨다: 다시 읽는다
            continue
        attachment = db.get(MessageAttachment, attachment_id)
        if attachment is None or attachment.group_id != group_id:
            db.commit()  # 그 사이 지워진 사진: 줄을 만들지 않는다(FK 를 검사하지 않는 SQLite 에서 고아 줄이 생기지 않게)
            return
        try:
            db.add(
                ChatPhotoCheck(
                    attachment_id=attachment_id,
                    group_id=group_id,
                    status=DOCUMENT,
                    source=MANUAL,
                    checked_at=now,
                )
            )
            db.flush()
            _add_event(
                db,
                group_id,
                attachment_id,
                actor_user_id,
                None,
                DOCUMENT,
                REASON_FAMILY_DOCUMENT,
                now,
            )
            db.commit()
            return
        except IntegrityError:  # 동시에 다른 요청이 줄을 만들었다: 처음부터 다시 읽는다
            db.rollback()
    raise RuntimeError("photo check changed concurrently")


def confirm_general(
    db: Session, group_id: str, attachment_id: str, actor_user_id: str, now: datetime | None = None
) -> str:
    """업로더가 "일반 사진이에요"를 명시적으로 확인했다(D-13). 결과 문자열:
    `confirmed`(photo/manual 로 바꿈, 이력 한 줄) | `already`(이미 photo, 이력 없음) | `document`(문서라 막음, D-15·D-16: document→photo 는 MVP 차단)
    | `in_progress`(pending 이고 15분 안 지남) | `missing`(줄이 없다: 예전 사진·지워진 사진, 확인 대상이 아니다).
    상태 변경은 `WHERE status=<읽은 값>` 조건부 UPDATE 하나라 자동 판별·다른 요청과 겹쳐도 한쪽만 이긴다. 업로더·방 종류 검사는 부르는 쪽."""
    now = now or datetime.now(UTC)
    for _ in range(3):
        row = db.execute(
            select(ChatPhotoCheck.status, ChatPhotoCheck.created_at)
            .where(
                ChatPhotoCheck.attachment_id == attachment_id, ChatPhotoCheck.group_id == group_id
            )
            .with_for_update()
        ).first()
        if row is None:
            db.commit()
            return "missing"
        if row.status == PHOTO:
            db.commit()
            return "already"
        if row.status == DOCUMENT:
            db.commit()
            return "document"
        conditions = [
            ChatPhotoCheck.attachment_id == attachment_id,
            ChatPhotoCheck.group_id == group_id,
            ChatPhotoCheck.status == row.status,
        ]
        if row.status == PENDING:
            cutoff = now - STALE_PENDING
            created = row.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if created > cutoff:
                db.commit()
                return "in_progress"
            conditions.append(ChatPhotoCheck.created_at <= cutoff)
        result = db.execute(
            update(ChatPhotoCheck)
            .where(*conditions)
            .values(status=PHOTO, source=MANUAL, last_error=None, checked_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            _add_event(
                db,
                group_id,
                attachment_id,
                actor_user_id,
                row.status,
                PHOTO,
                REASON_UPLOADER_CONFIRMED,
                now,
            )
            db.commit()
            return "confirmed"
        db.rollback()  # 읽은 뒤 바뀌었다(자동 결과·다른 확인): 다시 읽어 알맞은 답을 낸다
    raise RuntimeError("photo check changed concurrently")


def exclude_photo(
    db: Session, group_id: str, attachment_id: str, actor_user_id: str, now: datetime | None = None
) -> str:
    """업로더가 일반 사진을 타임라인에서 뺀다(`photo`→`excluded`/수동, 이력 한 줄). 결과 문자열:
    `excluded`(뺐다) | `already`(이미 뺐다, 이력 없음) | `not_in_timeline`(`photo` 가 아니라 뺄 것이 없다) | `missing`(줄이 없다).
    다시 넣는 것은 `confirm_general`(안내 확인 포함)이 한다. `WHERE status='photo'` 조건부 UPDATE 하나라 겹친 요청과도 한쪽만 이긴다.
    업로더·방 종류 검사는 부르는 쪽."""
    now = now or datetime.now(UTC)
    for _ in range(3):
        row = db.execute(
            select(ChatPhotoCheck.status)
            .where(
                ChatPhotoCheck.attachment_id == attachment_id, ChatPhotoCheck.group_id == group_id
            )
            .with_for_update()
        ).first()
        if row is None:
            db.commit()
            return "missing"
        if row.status == EXCLUDED:
            db.commit()
            return "already"
        if row.status != PHOTO:
            db.commit()
            return "not_in_timeline"
        result = db.execute(
            update(ChatPhotoCheck)
            .where(
                ChatPhotoCheck.attachment_id == attachment_id,
                ChatPhotoCheck.group_id == group_id,
                ChatPhotoCheck.status == PHOTO,
            )
            .values(status=EXCLUDED, source=MANUAL, last_error=None, checked_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            _add_event(
                db,
                group_id,
                attachment_id,
                actor_user_id,
                PHOTO,
                EXCLUDED,
                REASON_UPLOADER_REMOVED,
                now,
            )
            db.commit()
            return "excluded"
        db.rollback()  # 읽은 뒤 바뀌었다(문서로 저장 등): 다시 읽어 알맞은 답을 낸다
    raise RuntimeError("photo check changed concurrently")


def uploader_context(
    db: Session, group_id: str, attachment_id: str
) -> tuple[str, str, bool] | None:
    """(업로더 user_id, 방 종류, 메시지가 살아 있는가). 첨부가 없거나 다른 가족 것이면 None."""
    row = db.execute(
        select(Message.user_id, ChatRoom.kind, Message.deleted_at)
        .join(MessageAttachment, MessageAttachment.message_id == Message.id)
        .join(ChatRoom, ChatRoom.id == MessageAttachment.room_id)
        .where(MessageAttachment.id == attachment_id, MessageAttachment.group_id == group_id)
    ).first()
    if row is None:
        return None
    return row.user_id, row.kind, row.deleted_at is None


def _review_filter(group_id: str, user_id: str, cutoff: datetime, excluded: bool = False) -> list:
    status_filter = (
        ChatPhotoCheck.status == EXCLUDED
        if excluded
        else or_(
            ChatPhotoCheck.status.in_((UNSURE, FAILED)),
            and_(ChatPhotoCheck.status == PENDING, ChatPhotoCheck.created_at <= cutoff),
        )
    )
    return [
        ChatPhotoCheck.group_id == group_id,
        MessageAttachment.group_id == group_id,
        Message.user_id == user_id,
        Message.deleted_at.is_(None),
        ChatRoom.kind == FAMILY,
        MessageAttachment.kind == "image",
        status_filter,
    ]


def _review_base(stmt):
    return (
        stmt.select_from(ChatPhotoCheck)
        .join(MessageAttachment, MessageAttachment.id == ChatPhotoCheck.attachment_id)
        .join(Message, Message.id == MessageAttachment.message_id)
        .join(ChatRoom, ChatRoom.id == MessageAttachment.room_id)
    )


def list_review(
    db: Session,
    group_id: str,
    user_id: str,
    limit: int,
    before_message_id: int | None = None,
    now: datetime | None = None,
    excluded: bool = False,
) -> tuple[list[tuple[str, int, str, datetime, datetime | None]], int]:
    """업로더 본인의 "확인 필요" 사진: (attachment_id, message_id, status, created_at, taken_at) 최신순 + 전체 개수.
    unsure·failed 와 15분 넘은 pending 만(`excluded=True` 면 내가 타임라인에서 뺀 사진만), 가족 전체방·살아 있는 메시지·이미지만.
    다른 사람의 사진은 절대 섞이지 않는다. 조회 오류는 삼키지 않는다(호출한 쪽이 503 으로 답한다)."""
    cutoff = (now or datetime.now(UTC)) - STALE_PENDING
    where = _review_filter(group_id, user_id, cutoff, excluded)
    total = db.scalar(_review_base(select(func.count())).where(*where)) or 0
    stmt = _review_base(
        select(
            ChatPhotoCheck.attachment_id,
            Message.id,
            ChatPhotoCheck.status,
            MessageAttachment.created_at,
            MessageAttachment.taken_at,
        )
    ).where(*where)
    if before_message_id is not None:
        stmt = stmt.where(Message.id < before_message_id)
    rows = db.execute(stmt.order_by(Message.id.desc()).limit(limit)).all()
    return [(r[0], r[1], r[2], r[3], r[4]) for r in rows], int(total)


def list_timeline(
    db: Session,
    group_id: str,
    limit: int,
    before: tuple[datetime, int] | None = None,
) -> list[tuple[str, int, datetime, datetime | None, datetime, str | None, str]]:
    """가족 타임라인: 일반 사진(`photo`)으로 확인된 가족 전체방 사진만. 줄이 없거나 pending·unsure·failed·document·excluded 면 나오지
    않는다(fail-closed). (attachment_id, message_id, display_at, taken_at, created_at, batch_id, uploader_id) 를 최신순으로.
    `display_at` 은 촬영일(없으면 보낸 시각)이고, 같은 `batch_id` 묶음은 보이는 사진 중 가장 이른 값으로 맞춘다(Q4).
    `before` 는 이전 쪽 마지막 (display_at, message_id). 조회 오류는 삼키지 않는다(호출한 쪽이 503 으로 답한다)."""
    own_at = func.coalesce(MessageAttachment.taken_at, MessageAttachment.created_at)
    where = [
        ChatPhotoCheck.group_id == group_id,
        MessageAttachment.group_id == group_id,
        Message.deleted_at.is_(None),
        ChatRoom.kind == FAMILY,
        MessageAttachment.kind == "image",
        ChatPhotoCheck.status == PHOTO,
    ]
    batch_min = (
        _review_base(
            select(MessageAttachment.batch_id.label("batch_id"), func.min(own_at).label("min_at"))
        )
        .where(*where, MessageAttachment.batch_id.is_not(None))
        .group_by(MessageAttachment.batch_id)
        .subquery()
    )
    display_at = func.coalesce(batch_min.c.min_at, own_at).label("display_at")
    stmt = (
        _review_base(
            select(
                ChatPhotoCheck.attachment_id,
                Message.id,
                display_at,
                MessageAttachment.taken_at,
                MessageAttachment.created_at,
                MessageAttachment.batch_id,
                Message.user_id,
            )
        )
        .outerjoin(batch_min, batch_min.c.batch_id == MessageAttachment.batch_id)
        .where(*where)
    )
    if before is not None:
        b_at, b_id = before
        stmt = stmt.where(or_(display_at < b_at, and_(display_at == b_at, Message.id < b_id)))
    rows = db.execute(stmt.order_by(display_at.desc(), Message.id.desc()).limit(limit)).all()
    return [tuple(r) for r in rows]


def delete_for_attachment(db: Session, attachment_id: str) -> None:
    """첨부를 지울 때 함께 지운다(커밋은 부르는 쪽). SQLite 는 연쇄 삭제가 없어 코드로도 지운다."""
    db.execute(
        delete(ChatPhotoCheckEvent).where(ChatPhotoCheckEvent.attachment_id == attachment_id)
    )
    db.execute(delete(ChatPhotoCheck).where(ChatPhotoCheck.attachment_id == attachment_id))


def confirmed_photo_ids(db: Session, group_id: str, attachment_ids: list[str]) -> set[str]:
    """그중 "일반 사진으로 확인"(`photo`)된 첨부 id 만. 줄이 없거나 pending·unsure·failed·document 면 빠진다(fail-closed).
    조회 오류는 삼키지 않는다: 타임라인은 이 함수가 던지면 목록을 주지 않고 오류로 답해야 한다."""
    if not attachment_ids:
        return set()
    rows = db.scalars(
        select(ChatPhotoCheck.attachment_id).where(
            ChatPhotoCheck.group_id == group_id,
            ChatPhotoCheck.attachment_id.in_(attachment_ids),
            ChatPhotoCheck.status == PHOTO,
        )
    )
    return set(rows)
