import secrets
import uuid

from sqlalchemy.orm import Session

from app.shared.auth import ensure_group_member
from app.shared.errors import bad_request, not_found
from app.shared.location_consent import set_location_consent

from . import repository as repo
from .models import Group, Invite, User
from .schemas import GroupOut, MemberOut, SignupOut, UserCreate, UserOut

_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 헷갈리는 글자(0 O 1 I)는 뺀다


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        role=user.role,
        active_group_id=user.active_group_id,
        location_consent=user.location_consent_at is not None,
    )


def signup(db: Session, body: UserCreate) -> SignupOut:
    user = repo.add_user(
        db, User(id=_uid(), name=body.name.strip(), role=body.role, token=secrets.token_urlsafe(24))
    )
    if body.location_consent:
        set_location_consent(db, user, True, source="signup")
    return SignupOut(user=user_out(user), token=user.token)


def group_out(db: Session, group: Group) -> GroupOut:
    invite = repo.active_invite(db, group.id)
    return GroupOut(
        id=group.id,
        name=group.name,
        invite_code=invite.code if invite else None,
        members=[MemberOut(id=m.id, name=m.name, role=m.role) for m in repo.members(db, group.id)],
    )


def create_group(db: Session, user: User, name: str) -> GroupOut:
    group = Group(id=_uid(), name=name.strip(), owner_id=user.id)
    invite = Invite(
        code="".join(secrets.choice(_CODE_CHARS) for _ in range(8)),
        group_id=group.id,
        created_by=user.id,
    )
    repo.add_group(db, group, user, invite)
    return group_out(db, group)


def join_group(db: Session, user: User, code: str) -> GroupOut:
    invite = repo.find_invite(db, code.strip().upper())
    if invite is None:
        raise bad_request("invalid_invite", "초대 코드가 올바르지 않거나 더 이상 쓸 수 없어요")
    repo.join(db, invite.group_id, user)
    return group_out(db, repo.get_group(db, invite.group_id))


def my_group(db: Session, user: User) -> GroupOut:
    if not user.active_group_id:
        raise not_found("가족 그룹")
    ensure_group_member(db, user.id, user.active_group_id)
    group = repo.get_group(db, user.active_group_id)
    if group is None:
        raise not_found("가족 그룹")
    return group_out(db, group)
