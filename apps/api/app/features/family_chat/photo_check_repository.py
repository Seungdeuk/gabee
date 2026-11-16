"""사진 판별 상태(`chat_photo_checks`) DB 접근. 모든 쓰기는 조건부 UPDATE 하나로 끝내 늦게 오거나 겹쳐 온 결과가 상태를 덮어쓰지 못하게 한다."""

from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import ChatPhotoCheck, MessageAttachment

PENDING = "pending"
PHOTO = "photo"
DOCUMENT = "document"
UNSURE = "unsure"
FAILED = "failed"
STATUSES = frozenset({PENDING, PHOTO, DOCUMENT, UNSURE, FAILED})
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


def _set_manual_document(db: Session, group_id: str, attachment_id: str) -> int:
    result = db.execute(
        update(ChatPhotoCheck)
        .where(ChatPhotoCheck.attachment_id == attachment_id, ChatPhotoCheck.group_id == group_id)
        .values(status=DOCUMENT, source=MANUAL, last_error=None, checked_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


def mark_document_manual(db: Session, group_id: str, attachment_id: str) -> None:
    """사람이 "문서로 저장"을 눌렀다(D-15: 가족 누구나). 어떤 상태든 `document`(수동)로 맞춘다. 줄이 없는 예전 사진은 새로 만든다.
    문서로 숨기는 방향이라 안전하다. 이후 자동 판별은 이 줄을 바꾸지 못한다."""
    if _set_manual_document(db, group_id, attachment_id) == 0:
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
                    checked_at=datetime.now(UTC),
                )
            )
            db.flush()
        except IntegrityError:  # 동시에 다른 요청이 줄을 만들었다: 그 줄을 갱신한다
            db.rollback()
            _set_manual_document(db, group_id, attachment_id)
    db.commit()


def delete_for_attachment(db: Session, attachment_id: str) -> None:
    """첨부를 지울 때 함께 지운다(커밋은 부르는 쪽). SQLite 는 연쇄 삭제가 없어 코드로도 지운다."""
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
