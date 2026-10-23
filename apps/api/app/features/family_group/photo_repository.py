"""프로필 사진의 DB 접근(commit 은 호출한 서비스가 한다)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import GroupMember, User


def get_user(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def share_group(db: Session, user_id: str, other_id: str) -> bool:
    """두 사용자가 같은 가족 그룹의 구성원(group_members 기준)인지."""
    mine = GroupMember.__table__.alias("mine")
    theirs = GroupMember.__table__.alias("theirs")
    row = db.execute(
        select(mine.c.group_id)
        .join(theirs, theirs.c.group_id == mine.c.group_id)
        .where(mine.c.user_id == user_id, theirs.c.user_id == other_id)
        .limit(1)
    ).first()
    return row is not None


def set_photo(db: Session, user: User, path: str | None, when: datetime | None) -> None:
    user.profile_photo_path = path
    user.profile_photo_updated_at = when


def lock_user(db: Session, user_id: str) -> User | None:
    """사용자 행을 잠가(PostgreSQL FOR UPDATE, SQLite 는 무시) 최신 값을 읽는다. 사진 업로드·삭제를 한 줄로 세운다."""
    return db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
