"""가족 초대·가입 승인(PR 4-B)의 DB 접근. 판단은 join_service.py 가 한다.

상태를 바꾸는 쿼리는 전부 조건부 UPDATE 한 문장이라, 동시에 같은 요청이 와도 하나만 성공한다(commit 은 호출한 서비스)."""

from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from .models import GroupMember, Invite, InviteAttempt, JoinRequest, User


# ---------- 초대 코드 ----------
def usable_invite_clause(now: datetime):
    """폐기되지 않았고, 만료 전이며, 사용 횟수가 남은 초대(NULL = 제한 없음, 기존 코드)."""
    return (
        Invite.revoked.is_(False),
        or_(Invite.expires_at.is_(None), Invite.expires_at > now),
        or_(Invite.max_uses.is_(None), Invite.use_count < Invite.max_uses),
    )


def find_usable_invite(db: Session, code: str, now: datetime) -> Invite | None:
    return db.scalar(select(Invite).where(Invite.code == code, *usable_invite_clause(now)))


def consume_invite_use(db: Session, code: str, now: datetime) -> bool:
    """사용 횟수를 한 번 쓴다. 폐기·만료·소진이면 0행이라 False(검사와 증가가 한 문장이라 동시 제출에도 max_uses 를 넘지 않는다)."""
    result = db.execute(
        update(Invite)
        .where(Invite.code == code, *usable_invite_clause(now))
        .values(use_count=Invite.use_count + 1)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def revoke_active_invites(db: Session, group_id: str) -> None:
    db.execute(
        update(Invite)
        .where(Invite.group_id == group_id, Invite.revoked.is_(False))
        .values(revoked=True)
        .execution_options(synchronize_session=False)
    )


def add_invite(db: Session, invite: Invite) -> None:
    db.add(invite)


def active_invite(db: Session, group_id: str, now: datetime) -> Invite | None:
    """지금 쓸 수 있는 가장 최근 초대(폐기·만료·소진된 코드는 보여주지 않는다)."""
    return db.scalar(
        select(Invite)
        .where(Invite.group_id == group_id, *usable_invite_clause(now))
        .order_by(Invite.created_at.desc())
        .limit(1)
    )


# ---------- 멤버십 ----------
def member_roles(db: Session, group_id: str) -> dict[str, str]:
    return dict(
        db.execute(
            select(GroupMember.user_id, GroupMember.role).where(GroupMember.group_id == group_id)
        ).all()
    )


def get_membership(db: Session, group_id: str, user_id: str) -> GroupMember | None:
    return db.get(GroupMember, (group_id, user_id))


def add_member(db: Session, group_id: str, user_id: str) -> None:
    """항상 member 로 넣는다 — 권한(owner/admin)은 요청값으로 정해지지 않는다."""
    db.add(GroupMember(group_id=group_id, user_id=user_id, role="member"))


# ---------- 가입 요청 ----------
def add_join_request(db: Session, row: JoinRequest) -> None:
    db.add(row)


def get_join_request(db: Session, request_id: str) -> JoinRequest | None:
    return db.get(JoinRequest, request_id)


def pending_request(db: Session, group_id: str, user_id: str) -> JoinRequest | None:
    return db.scalar(
        select(JoinRequest).where(
            JoinRequest.group_id == group_id,
            JoinRequest.user_id == user_id,
            JoinRequest.status == "pending",
        )
    )


def latest_request_of(db: Session, user_id: str) -> JoinRequest | None:
    return db.scalar(
        select(JoinRequest)
        .where(JoinRequest.user_id == user_id)
        .order_by(JoinRequest.requested_at.desc(), JoinRequest.id.desc())
        .limit(1)
    )


def pending_with_users(db: Session, group_id: str) -> list[tuple[JoinRequest, User]]:
    rows = db.execute(
        select(JoinRequest, User)
        .join(User, User.id == JoinRequest.user_id)
        .where(JoinRequest.group_id == group_id, JoinRequest.status == "pending")
        .order_by(JoinRequest.requested_at)
    )
    return [(req, user) for req, user in rows]


def decide_request(
    db: Session, request_id: str, status: str, when: datetime, decided_by: str | None
) -> bool:
    """대기 중인 요청만 결정한다(승인·거절·취소 중 먼저 온 하나만 True)."""
    result = db.execute(
        update(JoinRequest)
        .where(JoinRequest.id == request_id, JoinRequest.status == "pending")
        .values(status=status, decided_at=when, decided_by=decided_by)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


# ---------- 시도 기록(레이트리밋) ----------
def record_attempt(
    db: Session, ip: str, user_id: str | None, invite_id: str | None, success: bool
) -> None:
    """코드 원문·해시는 저장하지 않는다. 매칭에 성공했을 때만 invite_id 를 남긴다."""
    db.add(InviteAttempt(ip=ip[:64], user_id=user_id, invite_id=invite_id, success=success))


def failure_times(
    db: Session, *, ip: str | None = None, user_id: str | None = None, since: datetime
) -> list[datetime]:
    """since 이후의 실패 시각(오래된 순). ip 와 user_id 중 하나로 센다."""
    column = InviteAttempt.ip if ip is not None else InviteAttempt.user_id
    value = ip[:64] if ip is not None else user_id
    return list(
        db.scalars(
            select(InviteAttempt.created_at)
            .where(
                InviteAttempt.success.is_(False), column == value, InviteAttempt.created_at > since
            )
            .order_by(InviteAttempt.created_at)
        )
    )
