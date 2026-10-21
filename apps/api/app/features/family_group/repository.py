from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Group, GroupMember, Invite, User


def add_user(db: Session, user: User) -> User:
    db.add(user)
    db.commit()
    return user


def get_group(db: Session, group_id: str) -> Group | None:
    return db.get(Group, group_id)


def add_group(db: Session, group: Group, owner: User, invite: Invite) -> Group:
    db.add_all([group, GroupMember(group_id=group.id, user_id=owner.id), invite])
    owner.active_group_id = group.id
    db.commit()
    return group


def find_invite(db: Session, code: str) -> Invite | None:
    return db.scalar(select(Invite).where(Invite.code == code, Invite.revoked.is_(False)))


def active_invite(db: Session, group_id: str) -> Invite | None:
    return db.scalar(select(Invite).where(Invite.group_id == group_id, Invite.revoked.is_(False)))


def is_member(db: Session, group_id: str, user_id: str) -> bool:
    return db.get(GroupMember, (group_id, user_id)) is not None


def join(db: Session, group_id: str, user: User) -> None:
    if not is_member(db, group_id, user.id):
        db.add(GroupMember(group_id=group_id, user_id=user.id))
    user.active_group_id = group_id
    db.commit()


def members(db: Session, group_id: str) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .join(GroupMember, GroupMember.user_id == User.id)
            .where(GroupMember.group_id == group_id)
            .order_by(GroupMember.joined_at)
        )
    )
