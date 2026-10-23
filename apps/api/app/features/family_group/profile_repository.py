"""가족 프로필·별명·관리자 지정(PR 4-C)의 DB 접근(commit 은 호출한 서비스가 한다)."""

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .models import GroupMember, MemberNickname


def get_membership(db: Session, group_id: str, user_id: str) -> GroupMember | None:
    return db.get(GroupMember, (group_id, user_id))


def set_member_role(db: Session, group_id: str, user_id: str, role: str) -> bool:
    """owner 가 아닌 구성원의 role 만 바꾼다(조건부 UPDATE 한 문장 — owner 행은 절대 건드리지 않는다)."""
    result = db.execute(
        update(GroupMember)
        .where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
            GroupMember.role != "owner",
        )
        .values(role=role)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def get_nickname(
    db: Session, group_id: str, owner_id: str, target_id: str
) -> MemberNickname | None:
    return db.get(MemberNickname, (group_id, owner_id, target_id))


def list_nicknames(db: Session, group_id: str, owner_id: str) -> list[MemberNickname]:
    """내가 쓴 것만(owner_user_id 가 요청자). 다른 사람이 쓴 별명·메모는 쿼리 자체에 나오지 않는다."""
    return list(
        db.scalars(
            select(MemberNickname)
            .where(MemberNickname.group_id == group_id, MemberNickname.owner_user_id == owner_id)
            .order_by(MemberNickname.target_user_id)
        )
    )


def upsert_nickname(
    db: Session,
    group_id: str,
    owner_id: str,
    target_id: str,
    nickname: str | None,
    memo: str | None,
    when: datetime,
) -> MemberNickname:
    row = get_nickname(db, group_id, owner_id, target_id)
    if row is None:
        row = MemberNickname(group_id=group_id, owner_user_id=owner_id, target_user_id=target_id)
        db.add(row)
    row.nickname, row.memo, row.updated_at = nickname, memo, when
    return row


def delete_nickname(db: Session, group_id: str, owner_id: str, target_id: str) -> None:
    db.execute(
        delete(MemberNickname).where(
            MemberNickname.group_id == group_id,
            MemberNickname.owner_user_id == owner_id,
            MemberNickname.target_user_id == target_id,
        )
    )
