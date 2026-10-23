"""Google·Kakao 로그인 토큰 검증(PR 4-D). 서버가 토큰을 직접 확인해 제공자 계정 id(`provider_uid`)를 뽑는다.

- Google: 앱이 시스템 브라우저 OAuth(PKCE)로 받은 **ID 토큰**을 Google 의 `tokeninfo` 로 서명 검증하고, 서버가 대상(aud)·발급자(iss)·만료를 다시 확인한다.
  (로컬 서명 검증은 `cryptography` 패키지가 필요해 의존성 승인을 받은 뒤 바꾼다 — 같은 `Identity` 를 돌려주므로 호출부는 그대로다.)
- Kakao: 앱이 받은 **액세스 토큰**을 Kakao API 로 다시 조회한다(토큰 정보로 우리 앱의 토큰인지 확인 → 사용자 정보).
- 설정이 비어 있으면(`GOOGLE_CLIENT_IDS`/`KAKAO_APP_ID`) 그 제공자는 `ProviderNotConfigured` 라 503 으로 막힌다. 비밀키는 서버(.env)에만 둔다.
- 토큰은 로그·오류 문구에 남기지 않는다.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.shared.config import settings

GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


@dataclass(frozen=True)
class Identity:
    provider: str
    uid: str
    email: str | None  # 제공자가 검증했다고 확인한 이메일만(아니면 None)
    name: str | None


class ProviderNotConfigured(Exception):
    """서버에 이 제공자의 앱 설정이 없다."""


class ProviderRejected(Exception):
    """토큰이 올바르지 않거나 우리 앱의 토큰이 아니거나 만료됐다."""


class ProviderUnavailable(Exception):
    """제공자 서버에 연결하지 못했다(일시 오류)."""


_overrides: dict[str, Callable[[str], Identity] | None] = {}


def set_verifier(provider: str, fn: Callable[[str], Identity] | None) -> None:
    """테스트용: 제공자 검증을 가짜로 바꾼다(None 이면 해제)."""
    _overrides[provider] = fn


def _fetch_json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers=headers or {})  # noqa: S310 - https 고정 주소만 쓴다
    try:
        with urlopen(request, timeout=settings.social_http_timeout_seconds) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (400, 401, 403):
            raise ProviderRejected from None
        raise ProviderUnavailable from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ProviderUnavailable from None


def _google(token: str) -> Identity:
    audiences = [a.strip() for a in settings.google_client_ids.split(",") if a.strip()]
    if not audiences:
        raise ProviderNotConfigured
    claims = _fetch_json(
        "https://oauth2.googleapis.com/tokeninfo?" + urlencode({"id_token": token})
    )
    try:
        expired = int(claims.get("exp", 0)) <= time.time()
    except (TypeError, ValueError):
        expired = True
    if (
        claims.get("aud") not in audiences
        or claims.get("iss") not in GOOGLE_ISSUERS
        or expired
        or not claims.get("sub")
    ):
        raise ProviderRejected
    verified = str(claims.get("email_verified", "")).lower() == "true"
    return Identity(
        "google", str(claims["sub"]), claims.get("email") if verified else None, claims.get("name")
    )


def _kakao(token: str) -> Identity:
    if not settings.kakao_app_id:
        raise ProviderNotConfigured
    headers = {"Authorization": f"Bearer {token}"}
    info = _fetch_json("https://kapi.kakao.com/v1/user/access_token_info", headers)
    if str(info.get("app_id")) != settings.kakao_app_id:  # 다른 앱에서 발급된 토큰
        raise ProviderRejected
    me = _fetch_json("https://kapi.kakao.com/v2/user/me", headers)
    if not me.get("id"):
        raise ProviderRejected
    account = me.get("kakao_account") or {}
    verified = bool(account.get("is_email_valid")) and bool(account.get("is_email_verified"))
    nickname = (account.get("profile") or {}).get("nickname")
    return Identity("kakao", str(me["id"]), account.get("email") if verified else None, nickname)


_REAL = {"google": _google, "kakao": _kakao}


def verify(provider: str, token: str) -> Identity:
    """제공자 토큰을 검증해 계정 정보를 돌려준다. 실패는 Provider* 예외."""
    override = _overrides.get(provider)
    return (override or _REAL[provider])(token)
