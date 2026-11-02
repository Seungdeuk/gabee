"""가족 프로필·별명·관리자 지정(PR 4-C)의 DB 접근(commit 은 호출한 서비스가 한다)."""

from datetime import datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from .models import GroupMember, MemberNickname, User


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


def delete_member_nicknames_of(db: Session, group_id: str, user_id: str) -> None:
    """이 그룹에서 user 가 쓴 별명과 user 에게 붙은 별명을 모두 지운다(복합 FK 때문에 멤버십 삭제보다 먼저)."""
    db.execute(
        delete(MemberNickname)
        .where(
            MemberNickname.group_id == group_id,
            or_(MemberNickname.owner_user_id == user_id, MemberNickname.target_user_id == user_id),
        )
        .execution_options(synchronize_session=False)
    )


def delete_member_if_not_owner(db: Session, group_id: str, user_id: str) -> bool:
    """owner 가 아닌 구성원의 멤버십만 지운다(조건부 DELETE 한 문장 — owner 행은 절대 지우지 않는다)."""
    result = db.execute(
        delete(GroupMember)
        .where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
            GroupMember.role != "owner",
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def lock_membership(db: Session, group_id: str, user_id: str) -> GroupMember | None:
    """내 멤버십 행을 잠그고 가져온다(PostgreSQL 은 FOR UPDATE, SQLite 는 무시)."""
    return db.scalars(
        select(GroupMember)
        .where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        .with_for_update()
    ).first()


def clear_active_group(db: Session, user_id: str, group_id: str) -> None:
    """활성 그룹이 이 그룹이면 남은 가족 중 가장 최근에 들어간 곳으로 바꾸고, 없으면 비운다."""
    fallback = (
        select(GroupMember.group_id)
        .where(GroupMember.user_id == user_id, GroupMember.group_id != group_id)
        .order_by(GroupMember.joined_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    db.execute(
        update(User)
        .where(User.id == user_id, User.active_group_id == group_id)
        .values(active_group_id=fallback)
        .execution_options(synchronize_session=False)
    )
