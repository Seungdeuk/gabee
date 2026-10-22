from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import Group, GroupMember, Invite, RefreshToken, User


def add_user(db: Session, user: User) -> User:
    db.add(user)
    db.commit()
    return user


def login_id_exists(db: Session, login_id: str) -> bool:
    return db.scalar(select(User.id).where(User.login_id == login_id)) is not None


def email_exists(db: Session, email: str) -> bool:
    return db.scalar(select(User.id).where(User.email == email)) is not None


def get_group(db: Session, group_id: str) -> Group | None:
    return db.get(Group, group_id)


def add_group(db: Session, group: Group, owner: User, invite: Invite) -> Group:
    # role 을 명시하지 않으면 GroupMember 의 기본값("member")이 적용돼 생성자가
    # owner 로 저장되지 않는다 — 반드시 role="owner" 를 직접 넘긴다.
    db.add_all([group, GroupMember(group_id=group.id, user_id=owner.id, role="owner"), invite])
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


def get_user_by_login_id(db: Session, login_id: str) -> User | None:
    return db.scalar(select(User).where(User.login_id == login_id))


def add_refresh_token(db: Session, token: RefreshToken) -> None:
    """저장만 한다(commit 은 호출한 서비스가 한다 — 회전은 폐기+발급을 한 트랜잭션으로 묶는다)."""
    db.add(token)


def find_refresh_token(db: Session, token_hash: str) -> RefreshToken | None:
    return db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))


def revoke_refresh_token_if_active(db: Session, token_id: str, when: datetime) -> bool:
    """아직 폐기되지 않은 경우에만 폐기한다(조건부 UPDATE 한 문장 → 동시 요청 중 하나만 True)."""
    result = db.execute(
        update(RefreshToken)
        .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=when)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def revoke_all_refresh_tokens(db: Session, user_id: str, when: datetime) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=when)
        .execution_options(synchronize_session=False)
    )
