"""가족 초대·가입 승인(PR 4-B) 업무 규칙.

- 초대 코드: 암호학적 난수 10자, 기본 24시간·1회. 재발급은 기존 코드를 폐기(삭제하지 않음)하고 새로 만든다.
- 참여: 코드가 맞으면 멤버십이 아니라 승인 대기 요청(join_requests)만 만든다. 관리자(owner/admin)가 승인해야 group_members 가 생긴다.
- 권한(owner/admin)은 어떤 요청값으로도 정해지지 않는다. 승인된 사람은 항상 member 로 들어가고, 관리자 판단은 DB 의 group_members.role 만 본다.
- 동시성: 사용 횟수 증가와 요청 결정은 전부 조건부 UPDATE 한 문장이라 동시 요청 중 하나만 성공한다.
- 시도 제한: 실패한 코드 입력은 invite_attempts 에 남기고(코드 원문·해시는 저장하지 않는다), 최근 15분 실패가 5회 이상이면 계정별·IP별로 막는다.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.errors import ApiError, bad_request, not_found

from . import join_repository as jrepo
from . import repository as repo
from .models import Group, Invite, JoinRequest, User, _uid

_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 헷갈리는 글자(0 O 1 I)는 뺀다
INVITE_CODE_LENGTH = 10
LEGACY_CODE_LENGTH = 8
MANAGER_ROLES = ("owner", "admin")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ---------- 초대 코드 ----------
def new_invite(group_id: str, created_by: str, now: datetime, *, legacy: bool = False) -> Invite:
    """새 정책(10자·24시간·1회)의 초대 코드. 저장은 호출한 쪽이 한다.
    legacy=True 는 기존 익명 계정이 만드는 그룹 전용 호환 코드(8자·만료/횟수 제한 없음, 승인 없이 바로 참여) — 익명 계정이 사라지면 쓰지 않는다."""
    if legacy:
        return Invite(
            code=_random_code(LEGACY_CODE_LENGTH), group_id=group_id, created_by=created_by
        )
    return Invite(
        code=_random_code(INVITE_CODE_LENGTH),
        group_id=group_id,
        created_by=created_by,
        expires_at=now + timedelta(seconds=settings.invite_ttl_seconds),
        max_uses=settings.invite_max_uses,
    )


def _random_code(length: int) -> str:
    return "".join(secrets.choice(_CODE_CHARS) for _ in range(length))


def require_manager(db: Session, user: User, group_id: str) -> None:
    membership = jrepo.get_membership(db, group_id, user.id)
    if membership is None:
        raise ApiError(403, "not_member", "이 가족 그룹의 구성원이 아니에요")
    if membership.role not in MANAGER_ROLES:
        raise ApiError(403, "not_manager", "가족 관리자만 할 수 있어요")


def is_manager(db: Session, user_id: str, group_id: str) -> bool:
    membership = jrepo.get_membership(db, group_id, user_id)
    return membership is not None and membership.role in MANAGER_ROLES


def _managed_group_id(db: Session, user: User) -> str:
    if not user.active_group_id:
        raise bad_request("no_group", "가족 그룹에 먼저 참여해 주세요")
    require_manager(db, user, user.active_group_id)
    return user.active_group_id


def reissue_invite(db: Session, user: User) -> Invite:
    """기존 코드를 모두 폐기하고 새 코드를 만든다(관리자만)."""
    group_id = _managed_group_id(db, user)
    jrepo.revoke_active_invites(db, group_id)
    invite = new_invite(group_id, user.id, datetime.now(UTC))
    jrepo.add_invite(db, invite)
    db.commit()
    return invite


def revoke_invite(db: Session, user: User) -> None:
    group_id = _managed_group_id(db, user)
    jrepo.revoke_active_invites(db, group_id)
    db.commit()


# ---------- 시도 제한 ----------
def _check_attempt_limit(db: Session, user_id: str | None, ip: str, now: datetime) -> None:
    window = timedelta(seconds=settings.invite_failure_window_seconds)
    limit = settings.invite_max_failures
    checks = [("ip", {"ip": ip})]
    if user_id is not None:
        checks.append(("user", {"user_id": user_id}))
    for _, key in checks:
        times = jrepo.failure_times(db, since=now - window, **key)
        if len(times) >= limit:
            # 슬라이딩 윈도우: 한도를 넘게 만든 가장 오래된 실패가 윈도우를 벗어나면 다시 시도할 수 있다
            release = _aware(times[len(times) - limit]) + window
            wait = max(1, int((release - now).total_seconds()) + 1)
            raise ApiError(
                429,
                "too_many_attempts",
                "초대 코드를 너무 많이 틀렸어요. 잠시 후 다시 시도해 주세요",
                headers={"Retry-After": str(wait)},
            )


def _fail_invalid(db: Session, user: User, ip: str) -> ApiError:
    """실패를 기록(커밋)하고 돌려줄 에러를 만든다. 없는 코드·폐기·만료·소진은 같은 응답이다(코드의 존재를 알려주지 않는다)."""
    jrepo.record_attempt(db, ip, user.id, None, False)
    db.commit()
    return bad_request("invalid_invite", "초대 코드가 올바르지 않거나 더 이상 쓸 수 없어요")


# ---------- 참여 ----------
def request_to_join(db: Session, user: User, code: str, ip: str) -> tuple[JoinRequest, Group]:
    """초대 코드로 승인 대기 요청을 만든다. 이미 같은 그룹에 대기 요청이 있으면 그것을 그대로 돌려준다(사용 횟수도 다시 쓰지 않는다)."""
    now = datetime.now(UTC)
    _check_attempt_limit(db, user.id, ip, now)
    code = code.strip().upper()
    invite = jrepo.find_usable_invite(db, code, now)
    if invite is None:
        raise _fail_invalid(db, user, ip)
    group_id, invite_id = invite.group_id, invite.id
    group = repo.get_group(db, group_id)
    if jrepo.get_membership(db, group_id, user.id) is not None:
        raise ApiError(409, "already_member", "이미 이 가족 그룹의 구성원이에요")
    existing = jrepo.pending_request(db, group_id, user.id)
    if existing is not None:
        return existing, group
    if not jrepo.consume_invite_use(db, code, now):  # 사이에 다른 사람이 마지막 사용 횟수를 썼다
        db.rollback()
        existing = jrepo.pending_request(
            db, group_id, user.id
        )  # 같은 사람의 동시 중복 제출이면 먼저 만든 요청
        if existing is not None:
            return existing, group
        raise _fail_invalid(db, user, ip)
    row = JoinRequest(
        id=_uid(), group_id=group_id, user_id=user.id, invite_id=invite_id, requested_at=now
    )
    jrepo.add_join_request(db, row)
    jrepo.record_attempt(db, ip, user.id, invite_id, True)
    try:
        db.commit()
    except IntegrityError:  # 같은 사람의 동시 요청이 먼저 대기 요청을 만들었다(부분 유니크 인덱스). 사용 횟수 증가도 함께 되돌아간다
        db.rollback()
        existing = jrepo.pending_request(db, group_id, user.id)
        if existing is None:
            raise
        return existing, group
    return row, group


def join_immediately(db: Session, user: User, code: str, ip: str) -> str:
    """기존 익명(레거시 토큰) 계정의 호환 경로: 승인 없이 바로 참여한다(그룹 id 반환). 전환이 끝나면(ALLOW_LEGACY_TOKEN_AUTH=false) 쓰이지 않는다.
    새 코드 정책(만료·횟수·시도 제한)은 똑같이 적용한다."""
    now = datetime.now(UTC)
    _check_attempt_limit(db, user.id, ip, now)
    code = code.strip().upper()
    invite = jrepo.find_usable_invite(db, code, now)
    if invite is None or not jrepo.consume_invite_use(db, code, now):
        db.rollback()
        raise _fail_invalid(db, user, ip)
    group_id = invite.group_id
    jrepo.record_attempt(db, ip, user.id, invite.id, True)
    db.flush()
    repo.join(db, group_id, user)  # commit 포함. 이미 구성원이면 조용히 넘어간다(기존 동작)
    return group_id


# ---------- 승인 · 거절 · 취소 ----------
def pending_for_manager(db: Session, user: User) -> list[tuple[JoinRequest, User]]:
    return jrepo.pending_with_users(db, _managed_group_id(db, user))


def _manageable_request(db: Session, manager: User, request_id: str) -> JoinRequest:
    """다른 그룹의 요청은 있는지조차 알려주지 않는다(404). 같은 그룹이지만 관리자가 아니면 403."""
    row = jrepo.get_join_request(db, request_id)
    if row is None:
        raise not_found("가입 요청")
    membership = jrepo.get_membership(db, row.group_id, manager.id)
    if membership is None:
        raise not_found("가입 요청")
    if membership.role not in MANAGER_ROLES:
        raise ApiError(403, "not_manager", "가족 관리자만 할 수 있어요")
    return row


def _already_decided() -> ApiError:
    return ApiError(409, "join_request_already_decided", "이미 처리된 가입 요청이에요")


def approve(db: Session, manager: User, request_id: str) -> str:
    """승인: 이때 비로소 group_members 행이 생긴다(항상 member). 그룹 id 를 돌려준다."""
    row = _manageable_request(db, manager, request_id)
    group_id, applicant_id = row.group_id, row.user_id
    if not jrepo.decide_request(db, request_id, "approved", datetime.now(UTC), manager.id):
        db.rollback()
        raise _already_decided()
    if jrepo.get_membership(db, group_id, applicant_id) is None:
        jrepo.add_member(db, group_id, applicant_id)
    applicant = db.get(User, applicant_id)
    if applicant is not None:
        applicant.active_group_id = group_id
    db.commit()
    return group_id


def reject(db: Session, manager: User, request_id: str) -> None:
    """거절: 사용한 초대 횟수는 돌려주지 않는다(시도 자체가 소모)."""
    _manageable_request(db, manager, request_id)
    if not jrepo.decide_request(db, request_id, "rejected", datetime.now(UTC), manager.id):
        db.rollback()
        raise _already_decided()
    db.commit()


def cancel(db: Session, user: User, request_id: str) -> None:
    """신청자가 자기 대기 요청을 취소한다."""
    row = jrepo.get_join_request(db, request_id)
    if row is None or row.user_id != user.id:
        raise not_found("가입 요청")
    if not jrepo.decide_request(db, request_id, "cancelled", datetime.now(UTC), user.id):
        db.rollback()
        raise _already_decided()
    db.commit()


def latest_request(db: Session, user: User) -> tuple[JoinRequest, Group] | None:
    row = jrepo.latest_request_of(db, user.id)
    if row is None:
        return None
    return row, repo.get_group(db, row.group_id)
