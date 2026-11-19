"""찰칵! 탐정단 가비 추천의 사진 문제 보관소: 한 사진 한 문제, 가족이 보낸 추천 추적, 삭제·동의 끔 정리.

- 행은 `PlayPhotoRec`(가족 앨범 사진은 `attachment_id` 유일, 흔한 사진은 `group_id` 가 빔).
- 가족이 보낸 추천은 `play_photos.rec_id` 와 `play_items`(가족·시각)를 조인해 안다(별도 사용 표가 없다).
- 채팅 사진을 지우면 그 사진의 행도 지운다(PostgreSQL 은 외래 키 연쇄 삭제, SQLite 는 `memory_hooks` 등록 콜백).
- 가족이 AI 동의를 끄면 그 가족의 사진 내용 질문(AI 가 만든 것) 행을 지운다(`ai_guard.on_disabled`).
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.features.family_chat.models import FAMILY, ChatRoom, MessageAttachment
from app.shared import ai_guard, memory_hooks

from .models import GAME_PHOTO, PlayItem, PlayPhoto, PlayPhotoRec

KIND_MONTH = 1
KIND_EVENT = 2
KIND_CONTENT = 3
SOURCE_ALBUM = 1
SOURCE_SEED = 3
SOURCE_AUTO = 4
RECENT_DAYS = 14  # 가족이 보낸 추천을 다시 안 보이는 기간(10~17일의 가운데)


def row_for_attachment(db: Session, attachment_id: str) -> PlayPhotoRec | None:
    """이 채팅 사진의 추천 행(없으면 None). 한 사진에 한 행뿐이다."""
    return db.scalar(select(PlayPhotoRec).where(PlayPhotoRec.attachment_id == attachment_id))


def rows_for_attachments(db: Session, attachment_ids: list[str]) -> dict[str, PlayPhotoRec]:
    """채팅 사진 id -> 추천 행(행이 있는 사진만)."""
    if not attachment_ids:
        return {}
    rows = db.scalars(select(PlayPhotoRec).where(PlayPhotoRec.attachment_id.in_(attachment_ids)))
    return {r.attachment_id: r for r in rows}


def family_image_attachments(db: Session, group_id: str, limit: int) -> list[MessageAttachment]:
    """가족 전체방의 사진 첨부를 최근순으로 `limit` 개(1:1 방·문서는 빠진다). 후보 거르기는 부르는 쪽."""
    stmt = (
        select(MessageAttachment)
        .join(ChatRoom, ChatRoom.id == MessageAttachment.room_id)
        .where(
            MessageAttachment.group_id == group_id,
            MessageAttachment.kind == "image",
            ChatRoom.kind == FAMILY,
        )
        .order_by(MessageAttachment.created_at.desc(), MessageAttachment.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def add_row(db: Session, **fields) -> PlayPhotoRec:
    """추천 행을 저장하고 커밋한다. 같은 `attachment_id` 가 이미 있으면 `IntegrityError`."""
    row = PlayPhotoRec(**fields)
    db.add(row)
    db.commit()
    return row


def sent_rec_ids(db: Session, group_id: str, now: datetime, days: int = RECENT_DAYS) -> set[str]:
    """이 가족이 최근 `days` 일 안에 가비 추천("이 문제로 쓰기")으로 보낸 추천 행 id."""
    since = now - timedelta(days=days)
    rows = db.scalars(
        select(PlayPhoto.rec_id)
        .join(PlayItem, PlayItem.id == PlayPhoto.play_id)
        .where(
            PlayItem.group_id == group_id,
            PlayItem.game == GAME_PHOTO,
            PlayItem.created_at >= since,
            PlayPhoto.rec_id.is_not(None),
        )
    )
    return set(rows)


def sent_today(db: Session, group_id: str, user_id: str, today_start: datetime) -> int:
    """오늘(`today_start` 이후) 이 사용자가 가비 추천으로 보낸 탐정단 문제 수."""
    return (
        db.scalar(
            select(func.count())
            .select_from(PlayPhoto)
            .join(PlayItem, PlayItem.id == PlayPhoto.play_id)
            .where(
                PlayItem.group_id == group_id,
                PlayItem.maker_id == user_id,
                PlayItem.game == GAME_PHOTO,
                PlayItem.created_at >= today_start,
                PlayPhoto.rec_id.is_not(None),
            )
        )
        or 0
    )


def purge_content_rows(db: Session, group_id: str) -> int:
    """그 가족의 사진 내용 질문(AI 가 만든 것) 행을 지운다. 월·일정 행과 흔한 사진 행은 AI 결과가 아니라 그대로 둔다. 지운 수를 돌려준다. 커밋은 부르는 쪽."""
    result = db.execute(
        delete(PlayPhotoRec).where(
            PlayPhotoRec.group_id == group_id, PlayPhotoRec.kind == KIND_CONTENT
        )
    )
    return result.rowcount or 0


def _on_attachment_removed(db: Session, group_id: str, attachment_id: str) -> None:
    """채팅 사진이 지워지면 그 사진의 추천 행도 지운다(PostgreSQL 은 외래 키가 이미 지웠고, 행이 없으면 아무 일도 없다)."""
    try:
        db.execute(delete(PlayPhotoRec).where(PlayPhotoRec.attachment_id == attachment_id))
        db.commit()
    except Exception:
        db.rollback()
        raise


ai_guard.on_disabled(purge_content_rows)
memory_hooks.register_attachment_removed(_on_attachment_removed)
