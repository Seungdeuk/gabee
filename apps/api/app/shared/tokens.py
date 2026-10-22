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


def _secret() -> str:
    global _ephemeral_secret
    if settings.jwt_secret:
        if len(settings.jwt_secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(f"JWT_SECRET 은 {MIN_SECRET_LENGTH}자 이상이어야 합니다")
        return settings.jwt_secret
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(48)
        log.warning(
            "JWT_SECRET 이 설정되지 않아 임시 비밀키를 씁니다(재시작하면 로그인이 풀려요). .env 에 설정하세요"
        )
    return _ephemeral_secret


def create_access_token(user_id: str, now: datetime | None = None) -> tuple[str, int]:
    """(JWT, 유효 초) 를 돌려준다."""
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
    }
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM), ttl


def verify_access_token(token: str) -> str:
    """유효한 Access Token 이면 사용자 id(sub) 를 돌려주고, 아니면 TokenError."""
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["iss", "aud", "sub", "iat", "exp", "jti", "token_use"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError(expired=True) from exc
    except (
        jwt.PyJWTError
    ) as exc:  # 서명 불일치, alg 불일치, 클레임 누락, 형식 오류, 아직 유효하지 않음 등
        raise TokenError from exc
    sub = claims["sub"]
    if claims["token_use"] != ACCESS_USE or not isinstance(sub, str) or not sub:
        raise TokenError
    return sub


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
