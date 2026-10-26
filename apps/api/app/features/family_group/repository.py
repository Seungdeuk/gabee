from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import (
    EmailVerification,
    Group,
    GroupMember,
    Invite,
    PasswordReset,
    RefreshToken,
    User,
)


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


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


# ---------- 이메일 인증 · 비밀번호 재설정 토큰 (원문은 저장하지 않고 해시만 다룬다) ----------
# 토큰은 한 번만 쓸 수 있고, 소비는 조건부 UPDATE 한 문장이라 동시 요청 중 하나만 성공한다(commit 은 호출한 서비스).


def supersede_email_verifications(db: Session, user_id: str, when: datetime) -> None:
    """새 인증 메일을 보내기 전에, 아직 쓰지 않은 이전 토큰을 만료시킨다(최신 메일의 토큰만 유효)."""
    db.execute(
        update(EmailVerification)
        .where(
            EmailVerification.user_id == user_id,
            EmailVerification.verified_at.is_(None),
            EmailVerification.expires_at > when,
        )
        .values(expires_at=when)
        .execution_options(synchronize_session=False)
    )


def add_email_verification(db: Session, row: EmailVerification) -> None:
    db.add(row)


def find_email_verification(db: Session, token_hash: str) -> EmailVerification | None:
    return db.scalar(select(EmailVerification).where(EmailVerification.token_hash == token_hash))


def consume_email_verification(db: Session, row_id: str, when: datetime) -> bool:
    result = db.execute(
        update(EmailVerification)
        .where(
            EmailVerification.id == row_id,
            EmailVerification.verified_at.is_(None),
            EmailVerification.expires_at > when,
        )
        .values(verified_at=when)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def mark_email_verified(db: Session, user_id: str, email: str, when: datetime) -> None:
    """토큰을 발급한 그 이메일이 아직 계정의 이메일일 때만 인증 처리한다."""
    db.execute(
        update(User)
        .where(User.id == user_id, User.email == email, User.email_verified_at.is_(None))
        .values(email_verified_at=when)
        .execution_options(synchronize_session=False)
    )


def supersede_password_resets(db: Session, user_id: str, when: datetime) -> None:
    db.execute(
        update(PasswordReset)
        .where(
            PasswordReset.user_id == user_id,
            PasswordReset.used_at.is_(None),
            PasswordReset.expires_at > when,
        )
        .values(used_at=when)
        .execution_options(synchronize_session=False)
    )


def add_password_reset(db: Session, row: PasswordReset) -> None:
    db.add(row)


def find_password_reset(db: Session, token_hash: str) -> PasswordReset | None:
    return db.scalar(select(PasswordReset).where(PasswordReset.token_hash == token_hash))


def consume_password_reset(db: Session, row_id: str, when: datetime) -> bool:
    result = db.execute(
        update(PasswordReset)
        .where(
            PasswordReset.id == row_id,
            PasswordReset.used_at.is_(None),
            PasswordReset.expires_at > when,
        )
        .values(used_at=when)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


# ---------- 6자리 코드 ----------
# 코드 확인은 "시도 횟수를 먼저 한 문장으로 올린 뒤" 비교한다 — 동시에 여러 번 찍어도 전체가 한도(failed_attempts < max)를 넘지 못한다.


def latest_active_email_verification(
    db: Session, user_id: str, when: datetime
) -> EmailVerification | None:
    return db.scalar(
        select(EmailVerification)
        .where(
            EmailVerification.user_id == user_id,
            EmailVerification.verified_at.is_(None),
            EmailVerification.expires_at > when,
        )
        .order_by(EmailVerification.expires_at.desc())
        .limit(1)
    )


def bump_email_code_attempt(db: Session, row_id: str, when: datetime, max_attempts: int) -> bool:
    result = db.execute(
        update(EmailVerification)
        .where(
            EmailVerification.id == row_id,
            EmailVerification.verified_at.is_(None),
            EmailVerification.expires_at > when,
            EmailVerification.failed_attempts < max_attempts,
        )
        .values(failed_attempts=EmailVerification.failed_attempts + 1)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def latest_active_password_reset(db: Session, user_id: str, when: datetime) -> PasswordReset | None:
    return db.scalar(
        select(PasswordReset)
        .where(
            PasswordReset.user_id == user_id,
            PasswordReset.used_at.is_(None),
            PasswordReset.expires_at > when,
        )
        .order_by(PasswordReset.expires_at.desc())
        .limit(1)
    )


def bump_reset_code_attempt(db: Session, row_id: str, when: datetime, max_attempts: int) -> bool:
    result = db.execute(
        update(PasswordReset)
        .where(
            PasswordReset.id == row_id,
            PasswordReset.used_at.is_(None),
            PasswordReset.expires_at > when,
            PasswordReset.failed_attempts < max_attempts,
        )
        .values(failed_attempts=PasswordReset.failed_attempts + 1)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
