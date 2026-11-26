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
# 타임라인 표시 선택(업로더의 명시적 포함·제외). **판별 상태(`chat_photo_checks.status`, 문서함 판정)를 바꾸지 않고** 이력 줄로만 남긴다 —
# 문서로 적힌 줄을 `photo`/`excluded` 로 덮으면 문서함 판정이 바뀌기 때문이다. 같은 첨부의 가장 최근 줄이 현재 선택이다(새 열·표 없음).
REASON_TIMELINE_INCLUDE = "timeline_include"
REASON_TIMELINE_EXCLUDE = "timeline_exclude"
TIMELINE_INCLUDE = "include"
TIMELINE_EXCLUDE = "exclude"
_TIMELINE_TO_STATUS = {
    TIMELINE_INCLUDE: "tl_include",
    TIMELINE_EXCLUDE: "tl_exclude",
}  # 이력의 to_status 자리(12자 이하). 판별 상태가 아니다
_TIMELINE_REASON = {
    TIMELINE_INCLUDE: REASON_TIMELINE_INCLUDE,
    TIMELINE_EXCLUDE: REASON_TIMELINE_EXCLUDE,
}
REASON_RECHECK = "recheck_requested"  # 업로더가 판별 실패·처리 지연 사진의 재검사를 요청했다(횟수는 이 이력 줄 수로 센다: 새 열 없음)
# 재검사: 사진 한 장당 최대 횟수와, 같은 사진을 다시 맡기기 전 기다리는 시간(겹친 요청·연타가 판별을 중복으로 돌리지 않게)
RECHECK_MAX = 3
RECHECK_COOLDOWN = timedelta(minutes=2)
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


def timeline_choices(db: Session, group_id: str) -> dict[str, str]:
    """가족의 타임라인 수동 선택 {첨부 id: "include" | "exclude"}(첨부마다 가장 최근 이력 줄). 선택한 사진만 들어 있어 작다.
    조회 오류는 삼키지 않는다(호출한 쪽이 503 으로 답한다)."""
    rows = db.execute(
        select(ChatPhotoCheckEvent.attachment_id, ChatPhotoCheckEvent.reason)
        .where(
            ChatPhotoCheckEvent.group_id == group_id,
            ChatPhotoCheckEvent.reason.in_((REASON_TIMELINE_INCLUDE, REASON_TIMELINE_EXCLUDE)),
        )
        .order_by(ChatPhotoCheckEvent.id)
    ).all()
    return {
        att: (TIMELINE_INCLUDE if reason == REASON_TIMELINE_INCLUDE else TIMELINE_EXCLUDE)
        for att, reason in rows
    }


def set_timeline_choice(
    db: Session,
    group_id: str,
    attachment_id: str,
    actor_user_id: str,
    choice: str,
    now: datetime | None = None,
) -> str:
    """타임라인 수동 선택을 적는다(`include`|`exclude`). 이미 같은 선택이면 `already`(이력 없음), 아니면 이력 한 줄을 더하고 `set`.
    판별 상태 줄(`chat_photo_checks`)은 건드리지 않는다. 업로더·방 종류 검사는 부르는 쪽."""
    current = timeline_choices(db, group_id).get(attachment_id)
    if current == choice:
        db.commit()
        return "already"
    status = db.scalar(
        select(ChatPhotoCheck.status).where(
            ChatPhotoCheck.attachment_id == attachment_id, ChatPhotoCheck.group_id == group_id
        )
    )
    _add_event(
        db,
        group_id,
        attachment_id,
        actor_user_id,
        status,
        _TIMELINE_TO_STATUS[choice],
        _TIMELINE_REASON[choice],
        now or datetime.now(UTC),
    )
    db.commit()
    return "set"


def uploaders_for(
    db: Session, group_id: str, attachment_ids: list[str]
) -> dict[str, tuple[str, datetime]]:
    """첨부 id → (올린 사람 id, 올린 시각). 이 가족의 살아 있는 가족 전체방 이미지만. 이미지 분석 동의(ADR 0020: 업로더 동의·소급 동의)를 확인할 때 쓴다."""
    if not attachment_ids:
        return {}
    rows = db.execute(
        _review_base(
            select(ChatPhotoCheck.attachment_id, Message.user_id, MessageAttachment.created_at)
        ).where(
            ChatPhotoCheck.group_id == group_id,
            MessageAttachment.group_id == group_id,
            Message.deleted_at.is_(None),
            ChatRoom.kind == FAMILY,
            MessageAttachment.kind == "image",
            ChatPhotoCheck.attachment_id.in_(attachment_ids),
        )
    ).all()
    return {att: (uploader, created) for att, uploader, created in rows}


def attachment_group(db: Session, attachment_id: str) -> str | None:
    """첨부가 속한 가족 id(없으면 None). 분석 작업이 결과를 쓰기 직전에 자격을 다시 확인할 때 쓴다."""
    return db.scalar(
        select(MessageAttachment.group_id).where(MessageAttachment.id == attachment_id)
    )


def image_attachment_ids(db: Session, group_id: str, uploader_id: str | None = None) -> list[str]:
    """이 가족의 이미지 첨부 id(올린 사람을 주면 그 사람 것만). 동의 철회·가족 비활성화 때 타임라인 분석 파일을 지우려고 쓴다."""
    stmt = (
        select(MessageAttachment.id)
        .join(Message, Message.id == MessageAttachment.message_id)
        .where(MessageAttachment.group_id == group_id, MessageAttachment.kind == "image")
    )
    if uploader_id is not None:
        stmt = stmt.where(Message.user_id == uploader_id)
    return list(db.scalars(stmt))


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
        excludable = (
            PHOTO,
            *AUTO_CANDIDATE_STATUSES,
        )  # 확인된 사진과, 분석을 통과해 자동 후보로 보이는 사진(문서·뺀 사진은 아니다)
        if row.status not in excludable:
            db.commit()
            return "not_in_timeline"
        result = db.execute(
            update(ChatPhotoCheck)
            .where(
                ChatPhotoCheck.attachment_id == attachment_id,
                ChatPhotoCheck.group_id == group_id,
                ChatPhotoCheck.status == row.status,
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
                row.status,
                EXCLUDED,
                REASON_UPLOADER_REMOVED,
                now,
            )
            db.commit()
            return "excluded"
        db.rollback()  # 읽은 뒤 바뀌었다(문서로 저장 등): 다시 읽어 알맞은 답을 낸다
    raise RuntimeError("photo check changed concurrently")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def recheck_counts(db: Session, attachment_ids: list[str]) -> dict[str, int]:
    """사진별 재검사 요청 횟수(이력 줄 수). 줄이 없는 사진은 0."""
    if not attachment_ids:
        return {}
    rows = db.execute(
        select(ChatPhotoCheckEvent.attachment_id, func.count())
        .where(
            ChatPhotoCheckEvent.attachment_id.in_(attachment_ids),
            ChatPhotoCheckEvent.reason == REASON_RECHECK,
        )
        .group_by(ChatPhotoCheckEvent.attachment_id)
    ).all()
    return {r[0]: int(r[1]) for r in rows}


def review_details(
    db: Session, group_id: str, attachment_ids: list[str]
) -> dict[str, tuple[str | None, int]]:
    """확인 필요 목록 한 쪽의 실패 종류 이름(`last_error`)과 재검사 횟수: {attachment_id: (last_error, 횟수)}."""
    if not attachment_ids:
        return {}
    errors = dict(
        db.execute(
            select(ChatPhotoCheck.attachment_id, ChatPhotoCheck.last_error).where(
                ChatPhotoCheck.group_id == group_id,
                ChatPhotoCheck.attachment_id.in_(attachment_ids),
            )
        ).all()
    )
    counts = recheck_counts(db, attachment_ids)
    return {a: (errors.get(a), counts.get(a, 0)) for a in attachment_ids}


def claim_recheck(
    db: Session, group_id: str, attachment_id: str, actor_user_id: str, now: datetime | None = None
) -> str:
    """판별 실패(`failed`) 또는 처리 지연(15분 넘은 `pending`)인 **자동** 줄을 다시 `pending` 으로 맡는다(판별을 실제로 다시 돌리는 것은 부르는 쪽).
    결과 문자열: `claimed`(맡았다: 이력 한 줄 + 판별을 다시 돌려야 함) | `in_progress`(이미 맡겨졌거나 아직 처리 중이다: 아무것도 바꾸지 않는다, 같은 요청을
    다시 보내도 같다) | `not_needed`(실패·지연이 아니다: unsure·photo·document·excluded 이거나 사람이 정한 줄) | `limit`(재검사 횟수를 다 썼다) | `missing`(줄이 없다).
    상태를 바꾸는 것은 `WHERE status=<읽은 값> AND checked_at=<읽은 값>` 조건부 UPDATE 하나라 겹친 요청은 한쪽만 맡는다. 결과가 `photo` 가 되는 길은 없다(D-13)."""
    now = now or datetime.now(UTC)
    for _ in range(3):
        row = db.execute(
            select(
                ChatPhotoCheck.status,
                ChatPhotoCheck.source,
                ChatPhotoCheck.created_at,
                ChatPhotoCheck.checked_at,
            )
            .where(
                ChatPhotoCheck.attachment_id == attachment_id, ChatPhotoCheck.group_id == group_id
            )
            .with_for_update()
        ).first()
        if row is None:
            db.commit()
            return "missing"
        if row.source != AUTO or row.status not in (PENDING, FAILED):
            db.commit()
            return "not_needed"
        cooled = row.checked_at is None or _utc(row.checked_at) <= now - RECHECK_COOLDOWN
        if row.status == PENDING:
            stale = _utc(row.created_at) <= now - STALE_PENDING
            if not (stale and cooled):
                db.commit()
                return "in_progress"  # 올린 지 얼마 안 됐거나 방금 맡겼다
        # failed 는 바로 다시 맡길 수 있다(맡으면 pending 이 되어, 겹친 요청은 위 분기에서 in_progress 로 끝난다)
        if recheck_counts(db, [attachment_id]).get(attachment_id, 0) >= RECHECK_MAX:
            db.commit()
            return "limit"
        same_checked = (
            ChatPhotoCheck.checked_at.is_(None)
            if row.checked_at is None
            else ChatPhotoCheck.checked_at == row.checked_at
        )
        result = db.execute(
            update(ChatPhotoCheck)
            .where(
                ChatPhotoCheck.attachment_id == attachment_id,
                ChatPhotoCheck.group_id == group_id,
                ChatPhotoCheck.status == row.status,
                ChatPhotoCheck.source == AUTO,
                same_checked,
            )
            .values(status=PENDING, last_error=None, checked_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            _add_event(
                db, group_id, attachment_id, actor_user_id, row.status, PENDING, REASON_RECHECK, now
            )
            db.commit()
            return "claimed"
        db.rollback()  # 읽은 뒤 바뀌었다(자동 결과·다른 재검사): 다시 읽어 알맞은 답을 낸다
    return "in_progress"


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


def _review_filter(
    group_id: str,
    user_id: str,
    cutoff: datetime,
    excluded: bool = False,
    choices: dict[str, str] | None = None,
) -> list:
    chosen = choices or {}
    out_ids = {a for a, c in chosen.items() if c == TIMELINE_EXCLUDE}
    in_ids = {a for a, c in chosen.items() if c == TIMELINE_INCLUDE}
    status_filter = (
        or_(
            # 예전 방식으로 뺀 줄(다시 넣기로 선택한 것은 제외) 또는 문서 줄 등에서 수동으로 뺀 사진
            and_(ChatPhotoCheck.status == EXCLUDED, ChatPhotoCheck.attachment_id.not_in(in_ids)),
            ChatPhotoCheck.attachment_id.in_(out_ids),
        )
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
    where = _review_filter(
        group_id, user_id, cutoff, excluded, timeline_choices(db, group_id) if excluded else None
    )
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


AUTO_CANDIDATE_STATUSES = (
    UNSURE,
)  # 타임라인 자동 분석 대상(ADR 0026 분석 범위): 판별이 끝난 애매(unsure)만. pending 은 판별이 끝날 때까지 보류, failed·document·excluded 는 자동 분석하지 않는다.
# 분석을 허용한다고 자동 공개가 안전하다는 뜻은 아니다: 자동 노출은 서버 스위치(기본 꺼짐)의 운영 승인 사항이다.


def list_auto_candidate_ids(db: Session, group_id: str, limit: int) -> list[str]:
    """타임라인 자동 후보가 될 수 있는 사진 id(최신 `limit` 장): 가족 전체방의 살아 있는 이미지 첨부이고 판별 줄이 자동(`auto`)의
    unsure 인 것. 대기(`pending`)·실패(`failed`)·문서(`document`)·직접 확인(`photo`)·뺀(`excluded`) 줄과 수동 줄은 포함하지 않는다."""
    stmt = (
        _review_base(select(ChatPhotoCheck.attachment_id))
        .where(
            ChatPhotoCheck.group_id == group_id,
            MessageAttachment.group_id == group_id,
            Message.deleted_at.is_(None),
            ChatRoom.kind == FAMILY,
            MessageAttachment.kind == "image",
            ChatPhotoCheck.status.in_(AUTO_CANDIDATE_STATUSES),
            ChatPhotoCheck.source == AUTO,
        )
        .order_by(MessageAttachment.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def list_timeline(
    db: Session,
    group_id: str,
    limit: int,
    before: tuple[datetime, int] | None = None,
    extra_ids: set[str] | None = None,
    include_ids: set[str] | None = None,
    exclude_ids: set[str] | None = None,
) -> list[tuple[str, int, datetime, datetime | None, datetime, str | None, str]]:
    """가족 타임라인: 일반 사진(`photo`)으로 확인된 가족 전체방 사진, 업로더가 직접 넣은 사진(`include_ids`), `extra_ids`(분석을 통과한 자동 unsure 후보)만.
    그 밖의 pending·unsure·failed·document·excluded 줄은 나오지 않는다(fail-closed, 문서 줄은 업로더가 넣어야만 보인다).
    (attachment_id, message_id, display_at, taken_at, created_at, batch_id, uploader_id) 를 최신순으로.
    `display_at` 은 촬영일(없으면 보낸 시각)이고, 같은 `batch_id` 묶음은 보이는 사진 중 가장 이른 값으로 맞춘다(Q4).
    `before` 는 이전 쪽 마지막 (display_at, message_id). 조회 오류는 삼키지 않는다(호출한 쪽이 503 으로 답한다)."""
    own_at = func.coalesce(MessageAttachment.taken_at, MessageAttachment.created_at)
    visible = ChatPhotoCheck.status == PHOTO
    if exclude_ids:
        visible = and_(
            visible, ChatPhotoCheck.attachment_id.not_in(exclude_ids)
        )  # 업로더가 뺀 사진은 직접 확인한 사진도 숨긴다
    if include_ids:
        visible = or_(
            visible, ChatPhotoCheck.attachment_id.in_(include_ids)
        )  # 업로더의 명시적 포함은 어떤 판별 상태보다 우선한다
    if extra_ids:
        # 자동 후보는 자동(auto)의 미확정 줄일 때만(그 사이 업로더가 뺐거나 문서로 바뀌었으면 즉시 빠진다)
        visible = or_(
            visible,
            and_(
                ChatPhotoCheck.attachment_id.in_(extra_ids),
                ChatPhotoCheck.status.in_(AUTO_CANDIDATE_STATUSES),
                ChatPhotoCheck.source == AUTO,
            ),
        )
    where = [
        ChatPhotoCheck.group_id == group_id,
        MessageAttachment.group_id == group_id,
        Message.deleted_at.is_(None),
        ChatRoom.kind == FAMILY,
        MessageAttachment.kind == "image",
        visible,
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
