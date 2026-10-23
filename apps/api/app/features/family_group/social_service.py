"""Google·Kakao 로그인과 계정 연동(PR 4-D) 업무 규칙.

- 로그인: 이미 연동된 (provider, uid) 면 그 계정으로 로그인. 아니면 같은 이메일의 기존 계정이 있는지 보고, **있으면 자동으로 합치지 않고**
  후보 안내(마스킹한 이메일)만 돌려준다 — 기존 방식으로 로그인한 뒤 연동해야 한다. 없으면 소셜 전용 계정(비밀번호 없음)을 새로 만든다.
- 이메일은 제공자가 검증했다고 확인한 것만 쓰고, 그 계정은 이메일 인증이 끝난 것으로 본다. 이메일이 없어도 가입된다.
- 연동: 로그인한 본인이 한다. 비밀번호가 있는 계정은 비밀번호를 다시 확인하고(틀림은 로그인 실패 제한에 센다), 이미 다른 계정에 연결된
  소셜 계정은 거부한다.
- 해제: 연동된 소셜 계정 수 + (비밀번호가 있으면 1)이 1 이하면 거부한다(마지막 로그인 수단 보호). 사용자 행을 잠가 동시 해제를 한 줄로 세운다.
"""

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared import tokens
from app.shared.config import settings
from app.shared.errors import ApiError, bad_request, not_found
from app.shared.passwords import verify_password

from . import credentials, service
from . import repository as repo
from . import social_providers as providers
from . import social_repository as srepo
from .models import SocialAccount, User, _uid
from .schemas import LoginOut
from .social_schemas import SocialCandidateOut, SocialLinkIn, SocialLoginIn

_KEY = "social-ip:"


def mask_email(email: str) -> str:
    """j***@example.com — 이메일이 있다는 것만 알리고 주소는 알려주지 않는다."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def _check_ip_limit(ip: str) -> None:
    limit = settings.login_max_failures_per_ip
    if not limit:
        return
    wait = service.login_limiter.retry_after(
        _KEY + ip, limit, settings.login_failure_window_seconds
    )
    if wait:
        raise ApiError(
            429,
            "too_many_attempts",
            "시도가 너무 많아요. 잠시 후 다시 시도해 주세요",
            headers={"Retry-After": str(wait)},
        )


def _verify(provider: str, token: str, ip: str) -> providers.Identity:
    """제공자 토큰 검증 실패를 사용자 에러로 바꾼다(토큰은 어디에도 남기지 않는다)."""
    _check_ip_limit(ip)
    try:
        return providers.verify(provider, token)
    except providers.ProviderNotConfigured:
        raise ApiError(
            503, "social_not_configured", "이 로그인 방식은 아직 서버에 설정되지 않았어요"
        ) from None
    except providers.ProviderRejected:
        service.login_limiter.record(_KEY + ip)
        raise ApiError(
            401, "social_token_invalid", "로그인 정보가 올바르지 않아요. 다시 시도해 주세요"
        ) from None
    except providers.ProviderUnavailable:
        raise ApiError(
            503, "social_unavailable", "로그인 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요"
        ) from None


def _session(db: Session, user: User, device_label: str | None) -> LoginOut:
    pair = service._issue_tokens(db, user, device_label, datetime.now(UTC))
    db.commit()
    return LoginOut(user=service.user_out(user), **pair.model_dump())


def login(
    db: Session, provider: str, body: SocialLoginIn, ip: str
) -> LoginOut | SocialCandidateOut:
    tokens.ensure_configured()
    identity = _verify(provider, body.provider_token, ip)
    account = srepo.find_account(db, provider, identity.uid)
    if account is not None:
        user = db.get(User, account.user_id)
        if user is None:
            raise ApiError(
                401, "social_token_invalid", "로그인 정보가 올바르지 않아요. 다시 시도해 주세요"
            )
        return _session(db, user, body.device_label)

    email = credentials.normalize_email(identity.email) if identity.email else None
    if email and repo.get_user_by_email(db, email) is not None:
        return SocialCandidateOut(masked_email=mask_email(email))  # 자동 병합 금지

    now = datetime.now(UTC)
    user = User(
        id=_uid(),
        name=" ".join((identity.name or "").split())[:40] or "가족",
        role=body.role,
        token=service._unusable_legacy_token(),
        email=email,
        email_verified_at=now
        if email
        else None,  # 제공자가 검증한 이메일이라 인증이 끝난 것으로 본다
    )
    try:
        repo.add_user(db, user)
        srepo.add_account(
            db,
            SocialAccount(
                id=_uid(),
                user_id=user.id,
                provider=provider,
                provider_uid=identity.uid,
                email_at_link=email,
            ),
        )
        db.commit()
    except IntegrityError:  # 동시 가입: 같은 소셜 계정/이메일을 다른 요청이 먼저 저장했다
        db.rollback()
        account = srepo.find_account(db, provider, identity.uid)
        if account is not None:
            return _session(db, db.get(User, account.user_id), body.device_label)
        return SocialCandidateOut(masked_email=mask_email(email or "?@?"))
    return _session(db, user, body.device_label)


def _reauthenticate(user: User, password: str | None) -> None:
    """비밀번호가 있는 계정은 연동 전에 비밀번호를 다시 확인한다. 틀림은 로그인 실패 제한에 센다."""
    if not user.password_hash:
        return
    if not password:
        raise bad_request("password_required", "계정 보안을 위해 비밀번호를 한 번 더 입력해 주세요")
    key = f"id:{user.login_id}"
    window = settings.login_failure_window_seconds
    wait = service.login_limiter.retry_after(key, settings.login_max_failures_per_id, window)
    if wait:
        raise ApiError(
            429,
            "too_many_attempts",
            "시도가 너무 많아요. 잠시 후 다시 시도해 주세요",
            headers={"Retry-After": str(wait)},
        )
    if not verify_password(user.password_hash, password):
        service.login_limiter.record(key)
        raise ApiError(401, "invalid_credentials", "비밀번호가 올바르지 않아요")
    service.login_limiter.clear(key)


def link(db: Session, user: User, provider: str, body: SocialLinkIn, ip: str) -> None:
    _reauthenticate(user, body.password)
    identity = _verify(provider, body.provider_token, ip)
    existing = srepo.find_account(db, provider, identity.uid)
    if existing is not None:
        if existing.user_id == user.id:
            return  # 이미 연결돼 있다(같은 결과)
        raise ApiError(
            409, "social_already_linked", "이 소셜 계정은 이미 다른 가비 계정에 연결돼 있어요"
        )
    if srepo.account_of(db, user.id, provider) is not None:
        raise ApiError(
            409,
            "social_provider_already_linked",
            "이 계정에는 이미 같은 종류의 소셜 계정이 연결돼 있어요",
        )
    srepo.add_account(
        db,
        SocialAccount(
            id=_uid(),
            user_id=user.id,
            provider=provider,
            provider_uid=identity.uid,
            email_at_link=identity.email,
        ),
    )
    try:
        db.commit()
    except IntegrityError:  # 동시에 같은 소셜 계정을 다른 계정에 연결하려 했다
        db.rollback()
        raise ApiError(
            409, "social_already_linked", "이 소셜 계정은 이미 다른 가비 계정에 연결돼 있어요"
        ) from None


def linked(db: Session, user: User) -> list[SocialAccount]:
    return srepo.accounts_of(db, user.id)


def unlink(db: Session, user: User, provider: str) -> None:
    """연동을 푼다. 로그인 수단이 하나도 남지 않게 되면 거부한다(사용자 행을 잠근 뒤 센다)."""
    locked = srepo.lock_user(db, user.id)
    if locked is None or srepo.account_of(db, user.id, provider) is None:
        db.rollback()
        raise not_found("연동된 소셜 계정")
    methods = srepo.count_accounts(db, user.id) + (1 if locked.password_hash else 0)
    if methods <= 1:
        db.rollback()
        raise ApiError(
            403,
            "last_login_method",
            "마지막 로그인 방법이라 해제할 수 없어요. 비밀번호를 만들거나 다른 계정을 먼저 연결해 주세요",
        )
    srepo.delete_account(db, user.id, provider)
    db.commit()
