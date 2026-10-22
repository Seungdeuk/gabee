import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared import tokens
from app.shared.auth import ensure_group_member
from app.shared.config import settings
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.location_consent import set_location_consent
from app.shared.passwords import hash_password, needs_rehash, verify_password
from app.shared.rate_limit import FailureLimiter

from . import credentials
from . import repository as repo
from .models import Group, Invite, RefreshToken, User
from .schemas import (
    AccountSignupIn,
    AccountSignupOut,
    GroupOut,
    LoginIdAvailableOut,
    LoginIn,
    LoginOut,
    MemberOut,
    RefreshIn,
    SignupOut,
    TokenOut,
    UserCreate,
    UserOut,
)

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
        login_id=user.login_id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
    )


def _unusable_legacy_token() -> str:
    """`users.token` 은 NOT NULL·unique 라 정식 회원에게도 값이 필요하다. 아무에게도 알려주지 않는 무작위 값이고,
    그와 별개로 shared/auth.py 가 정식 회원(login_id/password_hash 가 있는 계정)의 X-Gyeot-Token 인증을 거부한다."""
    return "nologin:" + secrets.token_urlsafe(32)


def signup_account(db: Session, body: AccountSignupIn) -> AccountSignupOut:
    """아이디/비밀번호/이메일 회원가입. 로그인(토큰 발급)은 하지 않는다 — 다음 단계(로그인 API)에서 한다."""
    login_id = credentials.normalize_login_id(body.login_id)
    email = credentials.normalize_email(body.email)
    name = credentials.normalize_name(body.name)
    credentials.validate_password(body.password, login_id, email)
    _ensure_available(db, login_id, email)
    user = User(
        id=_uid(),
        name=name,
        role=body.role,
        token=_unusable_legacy_token(),
        login_id=login_id,
        email=email,
        email_verified_at=None,  # 이메일 인증 전
        password_hash=hash_password(body.password),
    )
    try:
        repo.add_user(db, user)
    except IntegrityError:
        # 위 확인과 저장 사이에 같은 아이디/이메일이 먼저 저장된 경우(동시 가입) — DB 의 unique 제약이 최종 방어선이다.
        db.rollback()
        _ensure_available(db, login_id, email)
        raise
    return AccountSignupOut(user=user_out(user))


def _ensure_available(db: Session, login_id: str, email: str) -> None:
    if repo.login_id_exists(db, login_id):
        raise ApiError(409, "login_id_taken", "이미 사용 중인 아이디예요")
    if repo.email_exists(db, email):
        raise ApiError(409, "email_taken", "이미 가입된 이메일이에요")


def login_id_available(db: Session, raw: str) -> LoginIdAvailableOut:
    login_id = credentials.normalize_login_id(raw)
    return LoginIdAvailableOut(login_id=login_id, available=not repo.login_id_exists(db, login_id))


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


# ---------- 로그인 · 세션(Access/Refresh) ----------
login_limiter = FailureLimiter()  # 프로세스 메모리(shared/rate_limit.py 의 한계 참고)
_REUSE_GRACE = timedelta(
    seconds=10
)  # 동시 갱신 경쟁으로 폐기된 토큰이 곧바로 다시 오는 경우는 탈취로 보지 않는다
_dummy_hash: str | None = None


def _invalid_credentials() -> ApiError:
    # 존재하지 않는 아이디, 틀린 비밀번호, 비밀번호가 없는 계정(익명·소셜)을 같은 응답으로 처리한다
    return ApiError(401, "invalid_credentials", "아이디 또는 비밀번호가 올바르지 않아요")


def _aware(value: datetime) -> datetime:
    return (
        value if value.tzinfo else value.replace(tzinfo=UTC)
    )  # SQLite 는 시간대를 돌려주지 않는다


def _verify_with_constant_cost(password_hash: str | None, password: str) -> bool:
    """계정이 없을 때도 해시 검증 비용을 들여 응답 시간으로 계정 존재 여부를 알기 어렵게 한다."""
    global _dummy_hash
    if password_hash is None:
        if _dummy_hash is None:
            _dummy_hash = hash_password("dummy-password-for-timing-1")
        verify_password(_dummy_hash, password)
        return False
    return verify_password(password_hash, password)


def _issue_tokens(db: Session, user: User, device_label: str | None, now: datetime) -> TokenOut:
    """Access Token 과 새 Refresh Token 을 만든다. Refresh 는 해시만 저장한다(commit 은 호출자)."""
    refresh = tokens.new_refresh_token()
    ttl = settings.refresh_token_ttl_seconds
    repo.add_refresh_token(
        db,
        RefreshToken(
            id=_uid(),
            user_id=user.id,
            token_hash=tokens.hash_refresh_token(refresh),
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl),
            device_label=device_label,
        ),
    )
    access, access_ttl = tokens.create_access_token(user.id, now)
    return TokenOut(
        access_token=access, refresh_token=refresh, expires_in=access_ttl, refresh_expires_in=ttl
    )


def login(db: Session, body: LoginIn, ip: str) -> LoginOut:
    ip_key = f"ip:{ip}"
    try:
        login_id = credentials.normalize_login_id(body.login_id)
    except ApiError:
        login_limiter.record(ip_key)  # 형식이 틀린 아이디도 존재하지 않는 아이디와 같게 취급한다
        raise _invalid_credentials() from None
    id_key = f"id:{login_id}"
    window = settings.login_failure_window_seconds
    wait = max(
        login_limiter.retry_after(id_key, settings.login_max_failures_per_id, window),
        login_limiter.retry_after(ip_key, settings.login_max_failures_per_ip, window),
    )
    if wait:
        raise ApiError(
            429,
            "too_many_attempts",
            "로그인 시도가 너무 많아요. 잠시 후 다시 시도해 주세요",
            headers={"Retry-After": str(wait)},
        )

    user = repo.get_user_by_login_id(db, login_id)
    stored_hash = user.password_hash if user else None
    if not _verify_with_constant_cost(stored_hash, body.password):
        login_limiter.record(id_key)
        login_limiter.record(ip_key)
        raise _invalid_credentials()
    login_limiter.clear(id_key)

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(
            body.password
        )  # 해시 파라미터를 올린 뒤 첫 로그인 때 갱신
    pair = _issue_tokens(db, user, body.device_label, datetime.now(UTC))
    db.commit()
    return LoginOut(user=user_out(user), **pair.model_dump())


def refresh_session(db: Session, body: RefreshIn) -> TokenOut:
    """Refresh Token 회전: 쓴 토큰은 즉시 폐기하고 새 토큰을 발급한다(폐기+발급은 한 트랜잭션).
    같은 토큰으로 동시에 여러 요청이 와도 조건부 UPDATE 를 성공한 하나만 통과한다."""
    now = datetime.now(UTC)
    row = repo.find_refresh_token(db, tokens.hash_refresh_token(body.refresh_token))
    if row is None or _aware(row.expires_at) <= now:
        raise ApiError(401, "refresh_invalid", "로그인이 만료됐어요. 다시 로그인해 주세요")
    if not repo.revoke_refresh_token_if_active(db, row.id, now):
        # 이미 폐기된 토큰의 재사용. 폐기된 지 한참 뒤라면 탈취를 의심해 그 사용자의 모든 세션을 끊는다.
        db.rollback()
        db.refresh(row)
        revoked_at = row.revoked_at
        if revoked_at is not None and now - _aware(revoked_at) > _REUSE_GRACE:
            repo.revoke_all_refresh_tokens(db, row.user_id, now)
            db.commit()
        raise ApiError(401, "refresh_reused", "이미 사용된 로그인 정보예요. 다시 로그인해 주세요")
    user = db.get(User, row.user_id)
    if user is None:
        db.rollback()
        raise ApiError(401, "refresh_invalid", "로그인이 만료됐어요. 다시 로그인해 주세요")
    pair = _issue_tokens(db, user, row.device_label, now)
    db.commit()
    return pair


def logout(db: Session, body: RefreshIn) -> None:
    """이 세션(Refresh Token 하나)만 폐기한다. 모르는/만료/이미 폐기된 토큰도 같은 결과(멱등) — 토큰 존재 여부를 알려주지 않는다."""
    row = repo.find_refresh_token(db, tokens.hash_refresh_token(body.refresh_token))
    if row is not None:
        repo.revoke_refresh_token_if_active(db, row.id, datetime.now(UTC))
        db.commit()
