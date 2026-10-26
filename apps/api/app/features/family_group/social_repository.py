"""소셜 로그인(PR 4-D)의 DB 접근(commit 은 호출한 서비스가 한다)."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import SocialAccount, User


def find_account(db: Session, provider: str, uid: str) -> SocialAccount | None:
    return db.scalar(
        select(SocialAccount).where(
            SocialAccount.provider == provider, SocialAccount.provider_uid == uid
        )
    )


def accounts_of(db: Session, user_id: str) -> list[SocialAccount]:
    return list(
        db.scalars(
            select(SocialAccount)
            .where(SocialAccount.user_id == user_id)
            .order_by(SocialAccount.linked_at)
        )
    )


def account_of(db: Session, user_id: str, provider: str) -> SocialAccount | None:
    return db.scalar(
        select(SocialAccount).where(
            SocialAccount.user_id == user_id, SocialAccount.provider == provider
        )
    )


def has_account(db: Session, user_id: str) -> bool:
    return (
        db.scalar(select(SocialAccount.id).where(SocialAccount.user_id == user_id).limit(1))
        is not None
    )


def count_accounts(db: Session, user_id: str) -> int:
    return db.scalar(
        select(func.count()).select_from(SocialAccount).where(SocialAccount.user_id == user_id)
    )


def add_account(db: Session, row: SocialAccount) -> None:
    db.add(row)


def lock_user(db: Session, user_id: str) -> User | None:
    """이 사용자의 행을 잠근다(PostgreSQL FOR UPDATE). 같은 사용자의 동시 연동 해제 요청이 한 줄로 서도록 한다."""
    return db.scalar(select(User).where(User.id == user_id).with_for_update())


def delete_account(db: Session, user_id: str, provider: str) -> None:
    db.execute(
        delete(SocialAccount).where(
            SocialAccount.user_id == user_id, SocialAccount.provider == provider
        )
    )
