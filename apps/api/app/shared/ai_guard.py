"""AI 호출을 최소화하는 공통 관문. 가족 채팅 분석·답장 추천·문서 질문 등 모든 AI 기능이 이 함수 하나(`run`)를 거쳐 Anthropic 을 부른다.

순서(앞 단계에서 걸리면 Anthropic 을 부르지 않는다):
 1. 가족 그룹의 AI 동의(소유자·관리자가 켬) 확인
 2. 결과 캐시(가족 그룹별로 격리, 같은 요청은 TTL 안에서 다시 쓴다) — 적중하면 호출 0회
 3. 사용자 쿨다운, 사용자·가족 그룹별 하루 호출 한도
 4. 가족 그룹 동시 실행 제한(진행 중 표시를 DB 에 남겨 여러 워커에서도 같다)
 5. 사용 기록을 먼저 남겨(호출 수 1) 한도에 바로 반영 → 호출 → 토큰·결과로 기록 갱신, 결과 캐시 저장
호출은 기본 한 번이다(어시스턴트 채팅처럼 도구 루프를 쓰는 기능은 한 요청이 최대 4번 부르고 모두 센다). 실패해도 다시 시도하지 않고(한도에는 센다) 안전한 오류로 돌려준다.
모든 상태는 PostgreSQL(없으면 SQLite)에 있어 Redis 같은 새 인프라가 필요 없다. 대화·문서 원문과 API 키는 어디에도 저장·기록하지 않는다.
"""

import json
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared.ai_usage import AiGroupSetting, AiInflight, AiResultCache, AiUsageLog
from app.shared.config import settings
from app.shared.errors import ApiError
from app.shared.llm import client as llm


@dataclass(frozen=True)
class Outcome:
    result: dict
    cached: bool  # True 면 캐시에서 꺼냈고 Anthropic 을 부르지 않았다
    api_calls: int  # 이번 요청에서 실제로 부른 횟수(캐시 적중 0, 보통 1, 도구 루프 기능은 최대 4)
    input_tokens: int
    output_tokens: int
    model: str | None


# 동시 실행 칸을 이미 쥔 요청 안에서 부르는 호출(메인 채팅이 탭 에이전트를 부를 때)이 같은 가족의 칸을 또 잡으려다 거절되지 않게 한다
_slot_held_groups: ContextVar[frozenset[str]] = ContextVar(
    "ai_slot_held_groups", default=frozenset()
)

USAGE_RETENTION_DAYS = 90  # 사용 기록(원문 없음)을 남겨 두는 기간
CACHED_LOG_DEDUPE_SECONDS = 60  # 같은 사용자의 같은 캐시 적중 기록은 이 시간 안에 한 줄만 남긴다(반복 요청으로 표가 부푸는 것을 막는다)


# ---------- 동의 ----------
def is_enabled(db: Session, group_id: str) -> bool:
    row = db.get(AiGroupSetting, group_id)
    return bool(row and row.enabled)


def set_enabled(db: Session, group_id: str, user_id: str, enabled: bool) -> None:
    for _ in range(2):
        row = db.get(AiGroupSetting, group_id)
        if row is None:
            row = AiGroupSetting(group_id=group_id)
            db.add(row)
        row.enabled, row.enabled_by, row.updated_at = enabled, user_id, datetime.now(UTC)
        if not enabled:  # 동의를 끄면 이 가족의 분석 결과(대화에서 나온 요약·후보)도 바로 지운다
            db.execute(delete(AiResultCache).where(AiResultCache.group_id == group_id))
        try:
            db.commit()
            return
        except IntegrityError:  # 소유자·관리자가 거의 동시에 처음 켠 경우 — 다시 읽어서 갱신한다
            db.rollback()
    raise ApiError(409, "ai_busy", "설정을 바꾸는 중이에요. 잠시 뒤에 다시 시도해 주세요")


# ---------- 한도 ----------
@dataclass(frozen=True)
class Limits:
    """기능 묶음 하나의 쿨다운(초)과 하루 한도. 묶음마다 따로 센다."""

    cooldown_seconds: int
    per_user_per_day: int
    per_group_per_day: int


_BUCKETS: dict[str, tuple[Limits, tuple[str, ...]]] = {}


def register_bucket(name: str, limits: Limits, features: tuple[str, ...]) -> None:
    """features 에 든 기능은 기본 한도와 따로 센다. 이 기능들의 호출은 기본 묶음의 쿨다운·하루 한도·사용 횟수에서 빠진다.
    같은 이름으로 다시 부르면 덮어쓴다. 등록하지 않은 기능은 지금까지처럼 설정의 기본 한도를 함께 쓴다."""
    _BUCKETS[name] = (limits, features)


def _bucket_of(feature: str) -> tuple[Limits | None, tuple[str, ...] | None]:
    """(한도, 그 묶음의 기능들). 등록된 묶음이 아니면 (None, None) — 설정의 기본 한도를 쓴다."""
    for limits, features in _BUCKETS.values():
        if feature in features:
            return limits, features
    return None, None


def _only_bucket(query, features: tuple[str, ...] | None):
    """features 를 주면 그 묶음의 기록만, 안 주면 따로 센다고 등록된 기능을 뺀 나머지(기본 묶음)만 남긴다."""
    if features is not None:
        return query.where(AiUsageLog.feature.in_(features))
    separate = [f for _, fs in _BUCKETS.values() for f in fs]
    return query.where(AiUsageLog.feature.not_in(separate)) if separate else query


def day_start(now: datetime) -> datetime:
    """하루 한도를 세는 날짜 경계(기본 한국 시간 자정)를 UTC 로."""
    offset = timedelta(hours=settings.ai_day_utc_offset_hours)
    local = now + offset
    return local.replace(hour=0, minute=0, second=0, microsecond=0) - offset


def _calls_since(
    db: Session,
    since: datetime,
    *,
    user_id: str | None,
    group_id: str | None,
    features: tuple[str, ...] | None = None,
) -> int:
    query = select(func.coalesce(func.sum(AiUsageLog.api_calls), 0)).where(
        AiUsageLog.created_at >= since, AiUsageLog.api_calls > 0
    )
    query = _only_bucket(query, features)
    if user_id is not None:
        query = query.where(AiUsageLog.user_id == user_id)
    if group_id is not None:
        query = query.where(AiUsageLog.group_id == group_id)
    return int(db.scalar(query) or 0)


def usage_today(db: Session, user_id: str, group_id: str) -> tuple[int, int]:
    """(내 오늘 호출 수, 우리 가족 오늘 호출 수) — 캐시 적중은 세지 않는다."""
    since = day_start(datetime.now(UTC))
    return (
        _calls_since(db, since, user_id=user_id, group_id=None),
        _calls_since(db, since, user_id=None, group_id=group_id),
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _check_cooldown(
    db: Session, user_id: str, now: datetime, feature: str, exclude_id: int | None = None
) -> None:
    limits, features = _bucket_of(feature)
    cooldown = limits.cooldown_seconds if limits else settings.ai_request_cooldown_seconds
    if cooldown <= 0:
        return
    query = select(func.max(AiUsageLog.created_at)).where(
        AiUsageLog.user_id == user_id,
        AiUsageLog.api_calls > 0,
        AiUsageLog.created_at > now - timedelta(seconds=cooldown),
    )
    query = _only_bucket(query, features)
    if exclude_id is not None:  # 방금 내가 남긴 기록은 쿨다운 대상이 아니다
        query = query.where(AiUsageLog.id != exclude_id)
    last = db.scalar(query)
    if last is not None:
        wait = max(1, int((_aware(last) + timedelta(seconds=cooldown) - now).total_seconds()) + 1)
        raise ApiError(
            429,
            "ai_cooldown",
            "AI 요청은 잠시 간격을 두고 보낼 수 있어요. 조금 뒤에 다시 시도해 주세요",
            headers={"Retry-After": str(wait)},
        )


def _check_daily_limits(
    db: Session, user_id: str, group_id: str, feature: str, reserved: int = 0
) -> None:
    """reserved: 이미 내 기록(호출 1)이 들어 있어 한도 비교에서 빼야 하는 수(기록 뒤 재확인용)."""
    limits, features = _bucket_of(feature)
    since = day_start(datetime.now(UTC))
    user_calls = _calls_since(db, since, user_id=user_id, group_id=None, features=features)
    group_calls = _calls_since(db, since, user_id=None, group_id=group_id, features=features)
    user_calls, group_calls = user_calls - reserved, group_calls - reserved
    max_user = limits.per_user_per_day if limits else settings.ai_max_calls_per_user_per_day
    max_group = limits.per_group_per_day if limits else settings.ai_max_calls_per_group_per_day
    if user_calls >= max_user:
        raise ApiError(
            429,
            "ai_daily_limit_user",
            "오늘 쓸 수 있는 AI 요청 횟수를 모두 썼어요. 내일 다시 이용해 주세요",
        )
    if group_calls >= max_group:
        raise ApiError(
            429,
            "ai_daily_limit_group",
            "우리 가족이 오늘 쓸 수 있는 AI 요청 횟수를 모두 썼어요. 내일 다시 이용해 주세요",
        )


# ---------- 캐시 ----------
def _find_cache(db: Session, group_id: str, feature: str, key: str, now: datetime) -> dict | None:
    row = db.scalar(
        select(AiResultCache).where(
            AiResultCache.group_id == group_id,
            AiResultCache.feature == feature,
            AiResultCache.cache_key == key,
            AiResultCache.expires_at > now,
        )
    )
    return json.loads(row.result) if row else None


def _store_cache(
    db: Session, group_id: str, feature: str, key: str, result: dict, now: datetime
) -> None:
    ttl = settings.ai_result_cache_ttl_seconds
    if ttl <= 0:
        return
    db.execute(  # 같은 키와, 이미 만료된 이 가족의 결과를 함께 지운다(만료된 요약·후보가 남아 쌓이지 않게)
        delete(AiResultCache).where(
            AiResultCache.group_id == group_id,
            (AiResultCache.expires_at <= now)
            | ((AiResultCache.feature == feature) & (AiResultCache.cache_key == key)),
        )
    )
    db.execute(
        delete(AiUsageLog).where(AiUsageLog.created_at < now - timedelta(days=USAGE_RETENTION_DAYS))
    )
    db.add(
        AiResultCache(
            group_id=group_id,
            feature=feature,
            cache_key=key,
            result=json.dumps(result, ensure_ascii=False),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
    )
    try:
        db.commit()
    except IntegrityError:  # 다른 워커가 같은 결과를 먼저 저장했다 — 그대로 둔다
        db.rollback()


# ---------- 동시 실행 ----------
def _acquire_slot(
    db: Session, group_id: str, user_id: str, feature: str, now: datetime
) -> tuple[int, str]:
    db.execute(
        delete(AiInflight).where(
            AiInflight.group_id == group_id,
            AiInflight.started_at < now - timedelta(seconds=settings.ai_inflight_stale_seconds),
        )
    )
    db.commit()
    token = uuid.uuid4().hex
    for slot in range(max(1, settings.ai_max_concurrent_requests_per_group)):
        db.add(
            AiInflight(
                group_id=group_id,
                slot=slot,
                token=token,
                user_id=user_id,
                feature=feature,
                started_at=now,
            )
        )
        try:
            db.commit()
            return slot, token
        except IntegrityError:  # (group_id, slot) 가 이미 쓰이는 중 — 다음 칸을 본다
            db.rollback()
    raise ApiError(409, "ai_busy", "다른 AI 요청을 처리하고 있어요. 잠시 뒤에 다시 시도해 주세요")


def _release_slot(db: Session, group_id: str, slot: int, token: str) -> None:
    """내가 잡은 칸만 지운다 — 너무 오래 걸려 치워진 뒤 같은 칸을 잡은 다른 요청의 표시를 지우지 않는다."""
    db.rollback()
    db.execute(
        delete(AiInflight).where(
            AiInflight.group_id == group_id, AiInflight.slot == slot, AiInflight.token == token
        )
    )
    db.commit()


# ---------- 사용 기록 ----------
def _log(db: Session, **fields) -> AiUsageLog:
    row = AiUsageLog(**fields)
    db.add(row)
    db.commit()
    return row


def _log_cached(db: Session, user_id: str, group_id: str, feature: str, now: datetime) -> None:
    """캐시 적중도 기록하되(비용 0), 같은 사용자의 같은 적중은 짧은 시간 안에 한 줄만 남겨 표가 부푸는 것을 막는다."""
    recent = db.scalar(
        select(AiUsageLog.id)
        .where(
            AiUsageLog.group_id == group_id,
            AiUsageLog.user_id == user_id,
            AiUsageLog.feature == feature,
            AiUsageLog.status == "cached",
            AiUsageLog.created_at > now - timedelta(seconds=CACHED_LOG_DEDUPE_SECONDS),
        )
        .limit(1)
    )
    if recent is None:
        _log(
            db,
            group_id=group_id,
            user_id=user_id,
            feature=feature,
            api_calls=0,
            cache_hit=True,
            status="cached",
        )


def run(
    db: Session,
    *,
    user_id: str,
    group_id: str,
    feature: str,
    cache_key: str | None,
    call: Callable[[], tuple[dict, llm.JsonResult]],
) -> Outcome:
    """AI 기능 하나를 가드 아래에서 실행한다. call() 은 (검증이 끝난 결과, LLM 응답)을 돌려주고, 실패하면 llm.LLMUnavailable 이나 ValueError.
    cache_key 는 같은 요청이면 같아야 하고, 분석 범위가 바뀌면(새 메시지 등) 달라져야 한다(그래야 캐시가 갱신된다).
    cache_key=None 이면 결과를 캐시에 읽지도 쓰지도 않는다(대화처럼 같은 요청이 없고 원문을 남기면 안 되는 기능).
    call() 이 돌려준 응답에 `calls`(실제 Anthropic 호출 수, 1 이상)가 있으면 그 수를 사용 기록·한도에 센다(도구 루프처럼 한 요청이 여러 번 부르는 경우)."""
    if not is_enabled(db, group_id):
        raise ApiError(
            403,
            "ai_not_enabled",
            "가족 그룹에서 AI 기능을 아직 켜지 않았어요. 가족 소유자나 관리자가 켤 수 있어요",
        )
    now = datetime.now(UTC)
    cached = _find_cache(db, group_id, feature, cache_key, now) if cache_key is not None else None
    if cached is not None:
        _log_cached(db, user_id, group_id, feature, now)
        return Outcome(cached, True, 0, 0, 0, None)
    if not llm.available():
        raise ApiError(503, "llm_unavailable", "AI 기능이 아직 서버에 설정되지 않았어요")
    _check_cooldown(
        db, user_id, now, feature
    )  # 빠른 거절(경합이 있어도 아래에서 칸을 잡은 뒤 다시 확인한다)
    _check_daily_limits(db, user_id, group_id, feature)
    nested = (
        group_id in _slot_held_groups.get()
    )  # 바깥 요청이 이 가족의 칸을 쥐고 있다 — 한도·쿨다운은 그대로 센다
    slot, token = (0, "") if nested else _acquire_slot(db, group_id, user_id, feature, now)
    held = None if nested else _slot_held_groups.set(_slot_held_groups.get() | {group_id})
    try:
        # 칸을 잡는 사이 같은 결과를 다른 요청이 먼저 만들었을 수 있다 — AI 를 부르기 전에 한 번 더 본다
        cached = (
            _find_cache(db, group_id, feature, cache_key, datetime.now(UTC))
            if cache_key is not None
            else None
        )
        if cached is not None:
            _log_cached(db, user_id, group_id, feature, now)
            return Outcome(cached, True, 0, 0, 0, None)
        log = _log(
            db, group_id=group_id, user_id=user_id, feature=feature, api_calls=1, status="pending"
        )
        try:  # 기록(예약)을 남긴 뒤 한도·쿨다운을 다시 센다: 확인과 기록 사이에 끼어든 요청이 한도를 넘기지 못하게
            _check_cooldown(db, user_id, now, feature, exclude_id=log.id)
            _check_daily_limits(db, user_id, group_id, feature, reserved=1)
        except ApiError:
            db.rollback()
            log.api_calls, log.status = 0, "rejected"
            db.commit()
            raise
        try:
            result, response = call()
        except (llm.LLMUnavailable, ValueError) as exc:
            db.rollback()
            log.status = "error"
            log.api_calls = max(1, int(getattr(exc, "calls", 1)))  # 실패 전까지 부른 횟수
            log.error_code = "invalid_output" if isinstance(exc, ValueError) else "llm_failed"
            db.commit()
            raise ApiError(
                503, "llm_failed", "AI 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요"
            ) from None
        calls = max(1, int(getattr(response, "calls", 1)))
        log.status, log.model, log.api_calls = "ok", response.model, calls
        log.input_tokens, log.output_tokens = response.input_tokens, response.output_tokens
        db.commit()
        if cache_key is not None:
            _store_cache(db, group_id, feature, cache_key, result, now)
        return Outcome(
            result, False, calls, response.input_tokens, response.output_tokens, response.model
        )
    finally:
        if held is not None:
            _slot_held_groups.reset(held)
            _release_slot(db, group_id, slot, token)
