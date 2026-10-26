import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared import mailer, tokens
from app.shared.auth import ensure_group_member
from app.shared.config import settings
from app.shared.errors import ApiError, not_found
from app.shared.location_consent import set_location_consent
from app.shared.passwords import hash_password, needs_rehash, verify_password
from app.shared.rate_limit import FailureLimiter

from . import credentials, join_service, photo_service
from . import join_repository as jrepo
from . import repository as repo
from . import social_repository as srepo
from .join_schemas import JoinRequestOut
from .models import EmailVerification, Group, JoinRequest, PasswordReset, RefreshToken, User
from .schemas import (
    AccountSignupIn,
    AccountSignupOut,
    CodeIn,
    EmailRequestIn,
    EmailVerifiedOut,
    GroupOut,
    LoginIdAvailableOut,
    LoginIn,
    LoginOut,
    MemberOut,
    PasswordResetCodeConfirmIn,
    PasswordResetConfirmIn,
    RefreshIn,
    SignupOut,
    TokenIn,
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
        role_detail=user.role_detail,
        active_group_id=user.active_group_id,
        location_consent=user.location_consent_at is not None,
        login_id=user.login_id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        photo_url=photo_service.photo_url(user),
    )


def _unusable_legacy_token() -> str:
    """`users.token` 은 NOT NULL·unique 라 정식 회원에게도 값이 필요하다. 아무에게도 알려주지 않는 무작위 값이고,
    그와 별개로 shared/auth.py 가 정식 회원(login_id/password_hash 가 있는 계정)의 X-Gyeot-Token 인증을 거부한다."""
    return "nologin:" + secrets.token_urlsafe(32)


def signup_account(db: Session, body: AccountSignupIn) -> AccountSignupOut:
    """아이디/비밀번호/이메일 회원가입. 로그인(토큰 발급)은 하지 않는다 — 다음 단계(로그인 API)에서 한다."""
    login_id = credentials.normalize_login_id(body.login_id)
    # 이메일은 선택: 비어 있거나 공백뿐이면 없는 것으로 본다(적었다면 형식·중복은 그대로 검사한다)
    email = credentials.normalize_email(body.email) if body.email and body.email.strip() else None
    name = credentials.normalize_name(body.name)
    credentials.validate_password(body.password, login_id, email or "")
    role_detail = " ".join((body.role_detail or "").split()) if body.role == "other" else ""
    if len(role_detail) > 40:
        raise ApiError(400, "invalid_role_detail", "관계는 40자 이내로 적어 주세요")
    _ensure_available(db, login_id, email)
    user = User(
        id=_uid(),
        name=name,
        role=body.role,
        role_detail=role_detail or None,
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


def _ensure_available(db: Session, login_id: str, email: str | None) -> None:
    if repo.login_id_exists(db, login_id):
        raise ApiError(409, "login_id_taken", "이미 사용 중인 아이디예요")
    if email is not None and repo.email_exists(db, email):
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


def _member_out(user: User, row) -> MemberOut:
    return MemberOut(
        id=user.id,
        name=user.name,
        role=user.role,
        group_role=row.role if row else "member",
        display_name=row.display_name if row else None,
        family_relation=row.family_relation if row else None,
        family_relation_detail=row.family_relation_detail if row else None,
        photo_url=photo_service.photo_url(user),
    )


def group_out(db: Session, group: Group, viewer_id: str | None = None) -> GroupOut:
    """viewer_id 는 응답을 받는 사람. 초대 코드는 그 사람이 가족 관리자(owner/admin)일 때만 담긴다."""
    rows = jrepo.members_by_user(db, group.id)
    my_role = rows[viewer_id].role if viewer_id in rows else None
    invite = (
        jrepo.active_invite(db, group.id, datetime.now(UTC))
        if my_role in join_service.MANAGER_ROLES
        else None
    )
    return GroupOut(
        id=group.id,
        name=group.name,
        invite_code=invite.code if invite else None,
        invite_expires_at=invite.expires_at if invite else None,
        my_id=viewer_id if viewer_id in rows else None,
        my_role=my_role,
        members=[_member_out(m, rows.get(m.id)) for m in repo.members(db, group.id)],
    )


def _require_verified_email(user: User) -> None:
    """선택 정책(REQUIRE_EMAIL_VERIFICATION=true, 기본은 꺼짐 — 이메일이 없거나 인증하지 않아도 가족에 참여할 수 있다).
    켜면 이메일을 적었지만 인증하지 않은 정식 회원은 가족 그룹 생성·참여를 못 한다. 이메일이 없는 계정, 익명 계정, 메일 발송이
    설정되지 않은 환경(인증할 방법이 없음)에서는 켜도 적용하지 않는다."""
    if (
        settings.require_email_verification
        and mailer.get_mailer()
        is not None  # 인증 메일을 보낼 수 없는 환경에서는 막지 않는다(가입 후 막다른 길 방지)
        and user.login_id is not None
        and user.email is not None  # 이메일이 없는 계정은 인증할 수단이 없어 막지 않는다
        and user.email_verified_at is None
    ):
        raise ApiError(403, "email_not_verified", "이메일 인증을 먼저 완료해 주세요")


def create_group(db: Session, user: User, name: str) -> GroupOut:
    _require_verified_email(user)
    group = Group(id=_uid(), name=name.strip(), owner_id=user.id)
    # 정식 회원: 24시간·1회 코드. 기존 익명 계정: 호환을 위해 예전 방식 코드(만료·횟수 제한 없음). 어느 쪽이든 참여는 관리자 승인을 거친다
    invite = join_service.new_invite(
        group.id,
        user.id,
        datetime.now(UTC),
        legacy=user.login_id is None and not srepo.has_account(db, user.id),
    )
    repo.add_group(db, group, user, invite)
    return group_out(db, group, user.id)


def join_group(db: Session, user: User, code: str, ip: str = "unknown") -> JoinRequestOut:
    """초대 코드로 참여를 신청한다. 정식 회원이든 익명(레거시 토큰) 계정이든, 어떤 코드(레거시 코드 포함)를 쓰든 멤버십이 아니라
    승인 대기 요청만 만들어지고 관리자(owner/admin)가 승인해야 구성원이 된다. 승인 전에는 그룹 데이터에 접근할 수 없다."""
    _require_verified_email(user)
    row, group = join_service.request_to_join(db, user, code, ip)
    return join_request_out(row, group)


def join_request_out(row: JoinRequest, group: Group) -> JoinRequestOut:
    return JoinRequestOut(
        id=row.id,
        group_id=row.group_id,
        group_name=group.name,
        status=row.status,
        requested_at=row.requested_at,
        decided_at=row.decided_at,
    )


def group_out_by_id(db: Session, group_id: str, viewer_id: str) -> GroupOut:
    group = repo.get_group(db, group_id)
    if group is None:
        raise not_found("가족 그룹")
    return group_out(db, group, viewer_id)


def my_group(db: Session, user: User) -> GroupOut:
    if not user.active_group_id:
        raise not_found("가족 그룹")
    ensure_group_member(db, user.id, user.active_group_id)
    group = repo.get_group(db, user.active_group_id)
    if group is None:
        raise not_found("가족 그룹")
    return group_out(db, group, user.id)


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
    access, access_ttl = tokens.create_access_token(
        user.id, now, tokens.password_version(user.password_hash)
    )
    return TokenOut(
        access_token=access, refresh_token=refresh, expires_in=access_ttl, refresh_expires_in=ttl
    )


def login(db: Session, body: LoginIn, ip: str) -> LoginOut:
    tokens.ensure_configured()  # 로그인을 제공할 수 없는 설정이면 실패 횟수를 늘리기 전에 503
    ip_key = f"ip:{ip}"
    try:
        login_id = credentials.normalize_login_id(body.login_id)
    except ApiError:
        login_limiter.record(ip_key)  # 형식이 틀린 아이디도 존재하지 않는 아이디와 같게 취급한다
        raise _invalid_credentials() from None
    id_key = f"id:{login_id}"
    window = settings.login_failure_window_seconds
    limit_ip = settings.login_max_failures_per_ip
    wait = max(
        login_limiter.retry_after(id_key, settings.login_max_failures_per_id, window),
        login_limiter.retry_after(ip_key, limit_ip, window) if limit_ip else 0,
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
    tokens.ensure_configured()
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


# ---------- 이메일 인증 · 비밀번호 재설정 ----------
mail_limiter = FailureLimiter()  # 메일 요청 횟수(프로세스 메모리, login_limiter 와 같은 한계)
_HOUR = 3600
log = logging.getLogger(__name__)


def _link(path: str, token: str) -> str:
    base = settings.email_link_base
    if not base.endswith(("/", ":")):
        base += "/"
    return f"{base}{path}?token={token}"


def _code_hash(row_id: str, code: str) -> str:
    """6자리 코드는 경우의 수가 적어 해시만으로는 약하다 — 행 id 를 섞어 행마다 다르게 하고, 시도 횟수 제한(code_max_attempts)이 실제 방어선이다."""
    return hashlib.sha256(f"{row_id}:{code}".encode()).hexdigest()


def _new_token_row(row_cls, user_id: str, ttl: int, now: datetime, **extra):
    """(링크용 토큰 원문, 6자리 코드, 저장할 행). 원문과 코드는 메일에만 담기고 DB 에는 해시만 들어간다."""
    token = tokens.new_refresh_token()  # secrets.token_urlsafe(48), 용도만 다르다
    code = f"{secrets.randbelow(1_000_000):06d}"
    row_id = _uid()
    row = row_cls(
        id=row_id,
        user_id=user_id,
        token_hash=tokens.hash_refresh_token(token),
        code_hash=_code_hash(row_id, code),
        expires_at=now + timedelta(seconds=ttl),
        **extra,
    )
    return token, code, row


def _ttl_text(seconds: int) -> str:
    return f"{max(1, seconds // 3600)}시간" if seconds >= 3600 else f"{max(1, seconds // 60)}분"


def _check_rate(key: str, limit: int, window: int) -> None:
    wait = mail_limiter.retry_after(key, limit, window)
    if wait:
        raise ApiError(
            429,
            "too_many_requests",
            "요청이 너무 많아요. 잠시 후 다시 시도해 주세요",
            headers={"Retry-After": str(wait)},
        )


def deliver(mail: mailer.Mail, kind: str = "mail") -> None:
    """백그라운드 발송(응답 뒤). 실패해도 요청자에게 알리지 않는다 — 계정 존재 여부가 응답으로 새지 않게 하려는 것이다.
    대신 실패는 서버 로그에 ERROR 로 남긴다(`mail_delivery_failed kind=... reason=...`, 수신자·본문·토큰 제외)."""
    try:
        mailer.ensure_mail_configured().send(mail)
    except mailer.MailSendError as exc:
        log.error("mail_delivery_failed kind=%s reason=%s", kind, exc)
    except ApiError:
        log.error("mail_delivery_failed kind=%s reason=not_configured", kind)
    except Exception as exc:  # noqa: BLE001 - 백그라운드 작업의 예외는 어디에도 전달되지 않으므로 반드시 기록한다
        log.error("mail_delivery_failed kind=%s reason=%s", kind, type(exc).__name__)


def request_email_verification(db: Session, user: User) -> None:
    """로그인한 사용자의 인증 메일을 보낸다(재발송 겸용). 발송 실패는 호출자에게 503 으로 알린다."""
    sender = mailer.ensure_mail_configured()
    if user.login_id is None or not user.email:
        raise ApiError(400, "no_email", "이메일이 등록된 계정이 아니에요")
    if user.email_verified_at is not None:
        raise ApiError(409, "email_already_verified", "이미 인증된 이메일이에요")
    key = f"verify:{user.id}"
    _check_rate(f"{key}:cooldown", 1, settings.verify_resend_cooldown_seconds)
    _check_rate(f"{key}:hour", settings.verify_max_per_hour, _HOUR)
    now = datetime.now(UTC)
    token, code, row = _new_token_row(
        EmailVerification, user.id, settings.email_verify_ttl_seconds, now, email=user.email
    )
    repo.supersede_email_verifications(db, user.id, now)  # 이전 메일의 링크는 무효
    repo.add_email_verification(db, row)
    db.commit()
    mail_limiter.record(f"{key}:cooldown")
    mail_limiter.record(f"{key}:hour")
    body = "\n".join(
        [
            "가비 가족 비서 이메일 인증이에요.",
            "",
            f"앱에 아래 인증 코드 6자리를 입력해 주세요 ({_ttl_text(settings.email_verify_ttl_seconds)} 안에 한 번만 쓸 수 있어요).",
            f"인증 코드: {code}",
            "",
            "또는 아래 링크를 열면 자동으로 인증돼요.",
            _link("verify-email", token),
            "",
            "본인이 요청하지 않았다면 이 메일을 무시해 주세요.",
        ]
    )
    try:
        sender.send(mailer.Mail(to=user.email, subject="[가비] 이메일 인증", body=body))
    except mailer.MailSendError as exc:
        raise ApiError(
            503, "mail_send_failed", "메일을 보내지 못했어요. 잠시 후 다시 시도해 주세요"
        ) from exc


def _token_problem(row, now: datetime, used_value, kind: str) -> ApiError:
    if row is None:
        return ApiError(400, f"{kind}_invalid", "링크가 올바르지 않아요")
    if used_value is not None:
        return ApiError(400, f"{kind}_used", "이미 사용된 링크예요")
    if _aware(row.expires_at) <= now:
        return ApiError(400, f"{kind}_expired", "링크가 만료됐어요. 다시 요청해 주세요")
    return ApiError(400, f"{kind}_invalid", "링크가 올바르지 않아요")


def confirm_email_verification(db: Session, body: TokenIn) -> EmailVerifiedOut:
    now = datetime.now(UTC)
    row = repo.find_email_verification(db, tokens.hash_refresh_token(body.token))
    if row is None or not repo.consume_email_verification(db, row.id, now):
        if row is not None:
            db.rollback()
            db.refresh(row)
        raise _token_problem(row, now, row.verified_at if row else None, "verification")
    repo.mark_email_verified(db, row.user_id, row.email, now)  # 토큰 소비와 같은 트랜잭션
    db.commit()
    return EmailVerifiedOut()


def confirm_email_code(db: Session, user: User, body: CodeIn) -> EmailVerifiedOut:
    """로그인한 사용자가 메일의 6자리 코드로 인증한다. 코드(메일 1통)마다 code_max_attempts 번까지만 틀릴 수 있다."""
    if user.email_verified_at is not None:
        return EmailVerifiedOut()  # 이미 끝났다(다른 기기·링크로 먼저 인증): 같은 결과
    now = datetime.now(UTC)
    row = repo.latest_active_email_verification(db, user.id, now)
    if row is None or row.code_hash is None:
        raise ApiError(
            400, "verification_expired", "인증 코드가 만료됐어요. 인증 메일을 다시 받아 주세요"
        )
    row_id, stored, email = row.id, row.code_hash, row.email
    if not repo.bump_email_code_attempt(db, row_id, now, settings.code_max_attempts):
        db.rollback()
        raise ApiError(
            400, "verification_code_locked", "틀린 횟수를 넘었어요. 인증 메일을 다시 받아 주세요"
        )
    db.commit()  # 시도 횟수는 코드가 틀려도 남아야 한다
    if not hmac.compare_digest(stored, _code_hash(row_id, body.code)):
        raise ApiError(400, "verification_code_invalid", "인증 코드가 맞지 않아요")
    if not repo.consume_email_verification(db, row_id, now):
        db.rollback()
        raise ApiError(400, "verification_used", "이미 사용된 인증 코드예요")
    repo.mark_email_verified(db, user.id, email, now)
    db.commit()
    return EmailVerifiedOut()


def request_password_reset(db: Session, body: EmailRequestIn, ip: str) -> mailer.Mail | None:
    """재설정 메일을 만들어 돌려준다(발송은 router 가 응답 뒤 백그라운드로). 계정이 있든 없든 호출자에게는 똑같이 보인다 —
    메일 설정이 없을 때의 503 과 요청 제한 429 는 계정과 무관하게 같은 조건에서만 나온다."""
    mailer.ensure_mail_configured()
    email = credentials.normalize_email(body.email)
    _check_rate(f"reset-email:{email}", settings.reset_max_per_email_per_hour, _HOUR)
    if settings.reset_max_per_ip_per_hour:
        _check_rate(f"reset-ip:{ip}", settings.reset_max_per_ip_per_hour, _HOUR)
    mail_limiter.record(f"reset-email:{email}")
    mail_limiter.record(f"reset-ip:{ip}")
    user = repo.get_user_by_email(db, email)
    if user is None or user.login_id is None:  # 없는 이메일, 익명 계정: 아무것도 하지 않는다
        return None
    now = datetime.now(UTC)
    token, code, row = _new_token_row(
        PasswordReset, user.id, settings.password_reset_ttl_seconds, now
    )
    repo.supersede_password_resets(db, user.id, now)
    repo.add_password_reset(db, row)
    db.commit()
    body_text = "\n".join(
        [
            "가비 가족 비서 비밀번호 재설정 요청이에요.",
            "",
            f"앱에 아래 재설정 코드 6자리와 새 비밀번호를 입력해 주세요 ({_ttl_text(settings.password_reset_ttl_seconds)} 안에 한 번만 쓸 수 있어요).",
            f"재설정 코드: {code}",
            "",
            "또는 아래 링크를 열어 새 비밀번호를 설정할 수 있어요.",
            _link("reset-password", token),
            "",
            "본인이 요청하지 않았다면 이 메일을 무시해 주세요. 비밀번호는 바뀌지 않아요.",
        ]
    )
    return mailer.Mail(to=email, subject="[가비] 비밀번호 재설정", body=body_text)


def confirm_password_reset(db: Session, body: PasswordResetConfirmIn) -> None:
    now = datetime.now(UTC)
    row = repo.find_password_reset(db, tokens.hash_refresh_token(body.token))
    user = db.get(User, row.user_id) if row else None
    if row is None or user is None or row.used_at is not None or _aware(row.expires_at) <= now:
        raise _token_problem(row, now, row.used_at if row else None, "reset_token")
    _apply_password_reset(db, row.id, user, body.new_password, now)


def confirm_password_reset_code(db: Session, body: PasswordResetCodeConfirmIn) -> None:
    """메일의 6자리 코드와 이메일, 새 비밀번호로 재설정한다. 없는 이메일·익명 계정·틀린 코드·한도 초과는 모두 같은 응답이다(계정 존재 여부가 새지 않게)."""
    now = datetime.now(UTC)
    invalid = ApiError(
        400, "reset_code_invalid", "코드가 맞지 않거나 만료됐어요. 재설정 메일을 다시 받아 주세요"
    )
    user = repo.get_user_by_email(db, credentials.normalize_email(body.email))
    row = repo.latest_active_password_reset(db, user.id, now) if user and user.login_id else None
    if row is None or row.code_hash is None:
        raise invalid
    row_id, stored = row.id, row.code_hash
    if not repo.bump_reset_code_attempt(db, row_id, now, settings.code_max_attempts):
        db.rollback()
        raise invalid
    db.commit()  # 시도 횟수는 코드가 틀려도 남아야 한다
    if not hmac.compare_digest(stored, _code_hash(row_id, body.code)):
        raise invalid
    _apply_password_reset(db, row_id, user, body.new_password, now)


def _apply_password_reset(
    db: Session, row_id: str, user: User, new_password: str, now: datetime
) -> None:
    """토큰/코드 확인이 끝난 재설정을 적용한다(새 비밀번호 검사 → 한 번만 소비 → 모든 세션 폐기)."""
    # 새 비밀번호가 규칙에 맞는지 먼저 확인한다(틀려도 토큰은 소비되지 않아 다시 시도할 수 있다)
    credentials.validate_password(new_password, user.login_id or "", user.email or "")
    new_hash = hash_password(new_password)
    if not repo.consume_password_reset(db, row_id, now):  # 동시 요청 중 먼저 소비한 하나만 통과
        db.rollback()
        raise ApiError(400, "reset_token_used", "이미 사용된 링크예요")
    user.password_hash = new_hash
    repo.revoke_all_refresh_tokens(
        db, user.id, now
    )  # 모든 기기의 세션 폐기(Access Token 은 만료까지 유효)
    repo.supersede_password_resets(db, user.id, now)  # 같은 사용자의 다른 재설정 링크도 무효
    if user.email and user.email_verified_at is None:
        user.email_verified_at = (
            now  # 이 메일함에 도착한 링크로 재설정했으니 메일함 소유가 확인됐다
        )
    login_limiter.clear(
        f"id:{user.login_id}"
    )  # 새 비밀번호로 바로 로그인할 수 있게 실패 기록을 지운다
    db.commit()
