"""AI 추억 동의·설정 DB 접근. 채팅 표(첨부·메시지·방·사진 판별 상태)는 **읽기만** 하고, 다른 기능의 모델 파일을 import 하지 않도록
`Base.metadata` 의 표를 이름으로 찾는다(`shared/group_purge.py` 와 같은 방식). 판별 상태(`chat_photo_checks`)는 절대 쓰지 않는다(D-13)."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember
from app.shared.db import Base

from .models import FamilyMemorySetting, MemberMemoryConsent, PhotoAnalysisExclusion


# ---------- 가족 설정 ----------
def get_setting(db: Session, group_id: str) -> FamilyMemorySetting | None:
    return db.get(FamilyMemorySetting, group_id)


def family_enabled(db: Session, group_id: str) -> bool:
    row = db.get(FamilyMemorySetting, group_id)
    return bool(row and row.enabled)


def set_setting(db: Session, group_id: str, user_id: str, enabled: bool, now: datetime) -> None:
    """커밋은 부르는 쪽이 한다."""
    row = db.get(FamilyMemorySetting, group_id)
    if row is None:
        row = FamilyMemorySetting(group_id=group_id)
        db.add(row)
    row.enabled, row.updated_by, row.updated_at = enabled, user_id, now
    db.flush()


# ---------- 동의 ----------
def get_consent(db: Session, group_id: str, user_id: str) -> MemberMemoryConsent | None:
    return db.get(MemberMemoryConsent, (group_id, user_id))


def member_role(db: Session, group_id: str, user_id: str) -> str | None:
    membership = db.get(GroupMember, (group_id, user_id))
    return membership.role if membership is not None else None


# ---------- 사진별 제외 ----------
def is_excluded(db: Session, attachment_id: str) -> bool:
    return db.get(PhotoAnalysisExclusion, attachment_id) is not None


def add_exclusion(
    db: Session, group_id: str, user_id: str, attachment_id: str, now: datetime
) -> None:
    if db.get(PhotoAnalysisExclusion, attachment_id) is None:
        db.add(
            PhotoAnalysisExclusion(
                attachment_id=attachment_id, group_id=group_id, user_id=user_id, excluded_at=now
            )
        )
        db.flush()


def remove_exclusion(db: Session, attachment_id: str) -> None:
    db.execute(
        delete(PhotoAnalysisExclusion).where(PhotoAnalysisExclusion.attachment_id == attachment_id)
    )


# ---------- 채팅 사진 읽기(읽기 전용) ----------
@dataclass(frozen=True)
class PhotoContext:
    attachment_id: str
    group_id: str
    kind: str  # image | file
    uploader_id: str
    message_deleted: bool
    room_kind: str  # family | direct
    check_status: str | None  # chat_photo_checks.status. 줄이 없으면 None


def chat_tables_ready(db: Session) -> bool:
    return all(
        name in Base.metadata.tables
        for name in ("message_attachments", "messages", "chat_rooms", "chat_photo_checks")
    )


def photo_context(db: Session, attachment_id: str) -> PhotoContext | None:
    """사진(첨부) 하나의 자격 판정 입력. 첨부가 없으면(지워짐 포함) None."""
    if not chat_tables_ready(db):
        return None
    t = Base.metadata.tables
    att, msg, room, chk = (
        t["message_attachments"],
        t["messages"],
        t["chat_rooms"],
        t["chat_photo_checks"],
    )
    row = db.execute(
        select(
            att.c.id,
            att.c.group_id,
            att.c.kind,
            msg.c.user_id,
            msg.c.deleted_at,
            room.c.kind.label("room_kind"),
            chk.c.status,
        )
        .select_from(
            att.join(msg, msg.c.id == att.c.message_id)
            .join(room, room.c.id == att.c.room_id)
            .outerjoin(chk, chk.c.attachment_id == att.c.id)
        )
        .where(att.c.id == attachment_id)
    ).first()
    if row is None:
        return None
    return PhotoContext(
        attachment_id=row.id,
        group_id=row.group_id,
        kind=row.kind,
        uploader_id=row.user_id,
        message_deleted=row.deleted_at is not None,
        room_kind=row.room_kind,
        check_status=row.status,
    )
