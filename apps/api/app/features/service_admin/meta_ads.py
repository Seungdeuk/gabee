"""메타(페이스북·인스타그램) 광고 성과(읽기 전용). 마케팅 API 의 광고 계정 인사이트를 캠페인별로 가져온다.

새 의존성 없이 httpx 로 부른다. 토큰·광고 계정이 없으면 오류가 아니라 configured=false 를 돌려준다.
메타가 오류를 주거나 연결이 안 되면 ok=false 와 짧은 이유를 돌려주고 가짜 숫자를 섞지 않는다.
토큰은 Authorization 머리줄로만 보내고(주소에 넣지 않는다) 응답·로그에 남기지 않는다.
메타로 보내는 것은 광고 계정 번호와 기간뿐이고 회원·가족 데이터는 보내지 않는다. 결과는 10분 캐시한다.
docs/requirements/meta-ads.md 참고.
"""

import re
import threading
import time
from datetime import UTC, datetime

import httpx

from app.shared.config import settings

from .schemas import MetaAdsCampaign, MetaAdsOut, MetaAdsTotals

GRAPH = "https://graph.facebook.com"
FIELDS = "campaign_id,campaign_name,spend,impressions,clicks,actions,account_currency"
# 메타 문서(ads-action-stats)의 action_type 이름: 모바일 앱 설치, 모바일 앱 가입(앱 SDK 의 CompletedRegistration)
INSTALL = "mobile_app_install"
SIGNUP = "app_custom_event.fb_mobile_complete_registration"
PRESETS = {7: "last_7d", 30: "last_30d"}
ACCOUNT = re.compile(r"^(act_)?\d{1,30}$")
CACHE_SECONDS = 600  # 성공한 결과
FAIL_CACHE_SECONDS = 60  # 실패한 결과(메타를 계속 두드리지 않게)
MAX_PAGES = 5  # 한 쪽 100개 캠페인 × 5쪽
TIMEOUT = httpx.Timeout(5.0)
RATE_LIMIT_CODES = {4, 17, 32, 613}

_cache_lock = threading.Lock()  # 평가 초기화(evals/agent_eval/env.py)도 이 락을 잡고 비운다
_cache: dict[int, tuple[float, MetaAdsOut]] = {}


def _out(days: int, *, configured: bool, reason: str | None) -> MetaAdsOut:
    return MetaAdsOut(
        configured=configured,
        ok=False,
        reason=reason,
        days=days,
        currency=None,
        total=MetaAdsTotals(),
        campaigns=[],
        fetched_at=datetime.now(UTC),
    )


def _int(value: object) -> int:
    try:
        return int(float(value))  # 메타는 숫자를 글자("361324")로 준다
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _action(row: dict, kind: str) -> int:
    return sum(
        _int(a.get("value")) for a in row.get("actions") or [] if a.get("action_type") == kind
    )


def _reason(r: httpx.Response) -> str:
    """메타 오류를 관리자가 할 일이 보이는 짧은 문장으로 바꾼다. 메타의 원문 메시지는 싣지 않는다."""
    try:
        err = r.json().get("error") or {}
    except ValueError:
        err = {}
    code = err.get("code")
    if code == 190:
        return "메타 토큰이 만료됐거나 잘못됐어요. 새 토큰을 서버 환경변수에 넣어 주세요"
    if code in (10, 200) or r.status_code == 403:
        return "토큰에 광고 읽기 권한(ads_read)이 없거나 이 광고 계정에 접근할 수 없어요"
    if code in RATE_LIMIT_CODES or (isinstance(code, int) and 80000 <= code <= 80014):
        return "메타 요청 한도를 넘었어요. 잠시 뒤 다시 확인해 주세요"
    if code == 100:
        return "광고 계정 번호가 맞는지 확인해 주세요"
    return f"메타가 오류를 돌려줬어요(HTTP {r.status_code})"


def _collect(days: int) -> MetaAdsOut:
    token = settings.meta_ads_access_token.strip()
    account = settings.meta_ads_account_id.strip()
    if not token or not account:
        return _out(days, configured=False, reason="메타 광고 토큰·광고 계정이 서버에 아직 없어요")
    if not ACCOUNT.match(account):
        return _out(days, configured=False, reason="광고 계정 번호는 숫자(또는 act_숫자)여야 해요")
    if not account.startswith("act_"):
        account = f"act_{account}"

    url = f"{GRAPH}/{settings.meta_ads_api_version}/{account}/insights"
    headers = {"Authorization": f"Bearer {token}"}
    params: dict[str, str | int] = {
        "level": "campaign",
        "date_preset": PRESETS[days],
        "fields": FIELDS,
        "limit": 100,
    }
    campaigns: list[MetaAdsCampaign] = []
    currency: str | None = None
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            for _ in range(MAX_PAGES):
                r = client.get(url, params=params, headers=headers)
                if r.status_code != 200:
                    return _out(days, configured=True, reason=_reason(r))
                body = r.json()
                for row in body.get("data") or []:
                    currency = currency or row.get("account_currency")
                    campaigns.append(
                        MetaAdsCampaign(
                            campaign_id=str(row.get("campaign_id") or ""),
                            name=str(row.get("campaign_name") or "(이름 없음)"),
                            spend=round(_float(row.get("spend")), 2),
                            impressions=_int(row.get("impressions")),
                            clicks=_int(row.get("clicks")),
                            installs=_action(row, INSTALL),
                            signups=_action(row, SIGNUP),
                        )
                    )
                paging = body.get("paging") or {}
                after = (paging.get("cursors") or {}).get("after")
                if not paging.get("next") or not after:
                    break
                params = {**params, "after": after}
    except (httpx.HTTPError, ValueError, AttributeError):
        return _out(
            days, configured=True, reason="메타에 연결하지 못했어요. 잠시 뒤 다시 확인해 주세요"
        )

    campaigns.sort(key=lambda c: c.spend, reverse=True)
    total = MetaAdsTotals(
        spend=round(sum(c.spend for c in campaigns), 2),
        impressions=sum(c.impressions for c in campaigns),
        clicks=sum(c.clicks for c in campaigns),
        installs=sum(c.installs for c in campaigns),
        signups=sum(c.signups for c in campaigns),
    )
    return MetaAdsOut(
        configured=True,
        ok=True,
        reason=None,
        days=days,
        currency=currency,
        total=total,
        campaigns=campaigns,
        fetched_at=datetime.now(UTC),
    )


def meta_ads(days: int) -> MetaAdsOut:
    """최근 days(7 또는 30)일 캠페인별 광고 성과. 성공은 10분, 실패는 1분 캐시한다(설정이 없으면 캐시하지 않는다)."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(days)
        if hit and hit[0] > now:
            return hit[1]
    out = _collect(days)
    if out.configured:
        ttl = CACHE_SECONDS if out.ok else FAIL_CACHE_SECONDS
        with _cache_lock:
            _cache[days] = (now + ttl, out)
    return out
