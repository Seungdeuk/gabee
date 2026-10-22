"""Access Token(JWT) 발급·검증과 Refresh Token(불투명 무작위 문자열) 생성·해시.

- Access Token: HS256 고정, 클레임 iss/aud/sub/iat/exp/jti/token_use 필수. `token_use="access"` 만 받아서
  다른 용도의 토큰이 Bearer 로 통하지 않게 한다. 권한(role, 그룹)은 클레임에 넣지 않는다 — 요청마다 DB 로 확인한다.
- Refresh Token: JWT 가 아니라 `secrets.token_urlsafe(48)` 무작위 값. DB 에는 SHA-256 해시만 저장한다
  (엔트로피가 충분한 값이라 느린 해시가 필요 없다). 원문은 로그인/갱신 응답에서 한 번만 내려간다.
"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from .config import settings
from .errors import ApiError

log = logging.getLogger(__name__)

ALGORITHM = "HS256"  # 고정. 토큰 헤더의 alg 값은 신뢰하지 않는다
ACCESS_USE = "access"
MIN_SECRET_LENGTH = 32

_ephemeral_secret: str | None = None


class TokenError(Exception):
    """Access Token 검증 실패. `expired` 는 만료(재발급 필요), 아니면 위조·형식 오류."""

    def __init__(self, expired: bool = False) -> None:
        super().__init__("expired" if expired else "invalid")
        self.expired = expired


def _ephemeral_allowed() -> bool:
    """임시 비밀키는 로컬 개발(SQLite)이나 DEBUG=true 일 때만 허용한다. PostgreSQL(공용·운영)에서 DEBUG 없이
    JWT_SECRET 이 없으면 임시 키로 인증을 제공하지 않는다(재시작·다중 워커에서 깨지고, 설정 누락을 숨기기 때문)."""
    return settings.debug or settings.database_url.startswith("sqlite")


def _secret() -> str:
    """서명 비밀키. 쓸 수 없으면 503 `auth_not_configured` — 서버 시작과 레거시 인증·다른 API 는 영향이 없다."""
    global _ephemeral_secret
    if settings.jwt_secret:
        if len(settings.jwt_secret) < MIN_SECRET_LENGTH:
            log.error(
                "JWT_SECRET 이 %d자 미만이라 로그인/Bearer 인증을 쓸 수 없습니다", MIN_SECRET_LENGTH
            )
            raise ApiError(503, "auth_not_configured", "로그인 기능이 아직 설정되지 않았어요")
        return settings.jwt_secret
    if not _ephemeral_allowed():
        log.error(
            "JWT_SECRET 이 설정되지 않아 로그인/Bearer 인증을 쓸 수 없습니다(운영·공용 DB 에서는 임시 키를 쓰지 않음)"
        )
        raise ApiError(503, "auth_not_configured", "로그인 기능이 아직 설정되지 않았어요")
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(48)
        log.warning(
            "JWT_SECRET 이 설정되지 않아 임시 비밀키를 씁니다(재시작하면 로그인이 풀려요). .env 에 설정하세요"
        )
    return _ephemeral_secret


def ensure_configured() -> None:
    """서명 비밀키를 쓸 수 있는지 확인한다(안 되면 503 auth_not_configured)."""
    _secret()


def password_version(password_hash: str | None) -> str:
    """비밀번호 해시에서 파생한 짧은 값(해시 자체는 아니다). Access Token 에 넣어 두었다가 요청마다 현재 값과 비교하므로,
    비밀번호가 바뀌면(재설정·변경) 그 전에 발급된 Access Token 이 만료를 기다리지 않고 바로 무효가 된다."""
    return hashlib.sha256(("pv:" + (password_hash or "")).encode("utf-8")).hexdigest()[:16]


def create_access_token(user_id: str, now: datetime | None = None, pv: str = "") -> tuple[str, int]:
    """(JWT, 유효 초) 를 돌려준다. pv 는 password_version(사용자의 현재 password_hash)."""
    issued = now or datetime.now(UTC)
    ttl = settings.access_token_ttl_seconds
    claims = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": user_id,
        "iat": issued,
        "exp": issued + timedelta(seconds=ttl),
        "jti": secrets.token_hex(8),
        "token_use": ACCESS_USE,
        "pv": pv,
    }
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM), ttl


def verify_access_token(token: str) -> tuple[str, str]:
    """유효한 Access Token 이면 (사용자 id(sub), 비밀번호 버전(pv)) 을 돌려주고, 아니면 TokenError."""
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["iss", "aud", "sub", "iat", "exp", "jti", "token_use", "pv"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError(expired=True) from exc
    except (
        jwt.PyJWTError
    ) as exc:  # 서명 불일치, alg 불일치, 클레임 누락, 형식 오류, 아직 유효하지 않음 등
        raise TokenError from exc
    sub = claims["sub"]
    pv = claims["pv"]
    if (
        claims["token_use"] != ACCESS_USE
        or not isinstance(sub, str)
        or not sub
        or not isinstance(pv, str)
    ):
        raise TokenError
    return sub, pv


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
