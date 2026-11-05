"""서버 오류와 인증 실패를 ops_error_events 에 지문별로 합쳐 저장한다.

저장 대상은 5xx 응답, 처리되지 않은 예외, 401/403 이다(4xx 나머지는 저장하지 않는다). `app.shared.errors` 의 핸들러가
응답을 보내기 전에 요청 처리 안에서 `observe` 를 부른다(Cloud Run 요청 기반 CPU 에서 응답 뒤 작업이 유실될 수 있어서). 저장이 실패해도 예외를 삼키므로 응답은 그대로이고, 오류 응답에만 저장 시간이 더해진다.

저장하는 것: 오류 종류, 예외 클래스 이름 또는 응답 code, 메서드, 경로 패턴, 상태코드, 가린 메시지(200자), 발생 위치(파일:줄),
횟수, 처음·마지막 발생 시각, 마지막 trace id. 저장하지 않는 것: 사용자·가족 id, URL 원문, 요청 본문·헤더, 스택의 변수 값.
인증 실패(401/403)는 메시지를 저장하지 않고 응답 code(예: token_required)만 둔다.
"""

import hashlib
import logging
import time
import traceback
from datetime import UTC, datetime, timedelta

from fastapi import Request

from app.shared.config import settings
from app.shared.db import SessionLocal

from . import repository, service
from .masking import mask_message

logger = logging.getLogger(__name__)

SERVER_ERROR = "server_error"
AUTH_FAILURE = "auth_failure"
AUTH_STATUSES = frozenset({401, 403})
MAX_EVENT_TYPE_LENGTH = 100
PURGE_EVERY_SECONDS = 3600

_last_purge = 0.0


def classify(status: int) -> tuple[str, str] | None:
    """상태코드가 저장 대상이면 (종류, 심각도), 아니면 None."""
    if status >= 500:
        return SERVER_ERROR, "error"
    if status in AUTH_STATUSES:
        return AUTH_FAILURE, "warning"
    return None


def make_fingerprint(kind: str, event_type: str, route: str, status: int, message: str) -> str:
    """같은 오류를 한 행으로 묶는 키."""
    raw = "|".join((kind, event_type, route, str(status), message))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def error_location(exc: BaseException | None) -> str | None:
    """예외가 난 곳 중 우리 코드(app/ 아래)에서 가장 깊은 줄을 `app/...py:줄` 로 돌려준다. 변수 값은 쓰지 않는다."""
    tb = getattr(exc, "__traceback__", None)
    if tb is None:
        return None
    for frame in reversed(traceback.extract_tb(tb)):
        path = frame.filename.replace("\\", "/")
        i = path.rfind("/app/")
        if i != -1:
            return f"{path[i + 1 :]}:{frame.lineno}"[:200]
    return None


def observe(
    request: Request, status: int, code: str, message: str, exc: BaseException | None
) -> None:
    """저장 대상 오류를 기록한다. 꺼져 있거나 대상이 아니면 아무것도 하지 않고, 실패해도 예외를 내지 않는다."""
    if not settings.ops_errors_enabled:
        return
    try:
        classified = classify(status)
        if classified is None:
            return
        kind, severity = classified
        route = service.normalize_route(service.route_template(request.scope))
        if kind == AUTH_FAILURE:
            event_type, text, location = code, "", None
        else:
            event_type = type(exc).__name__ if exc is not None else code
            text = mask_message(message)
            location = error_location(exc)
        event_type = event_type[:MAX_EVENT_TYPE_LENGTH]
        method = request.method.upper()
        if method not in service.KNOWN_METHODS:
            method = "OTHER"
        state = request.scope.get("state") or {}
        trace_id = state.get("trace_id") if isinstance(state, dict) else None
        with SessionLocal() as db:
            repository.upsert_error_event(
                db,
                fingerprint=make_fingerprint(kind, event_type, route, status, text),
                kind=kind,
                severity=severity,
                event_type=event_type,
                method=method,
                route=route,
                status=status,
                message=text,
                location=location,
                trace_id=trace_id,
                now=datetime.now(UTC),
            )
            _purge_if_due(db)
    except (
        Exception
    ) as err:  # 기록 실패가 서버에 영향을 주면 안 된다. 로그에는 예외 클래스 이름만 남긴다
        logger.warning("ops error event record failed: %s", type(err).__name__)


def _purge_if_due(db) -> None:
    global _last_purge
    now = time.time()
    if now - _last_purge < PURGE_EVERY_SECONDS:
        return
    _last_purge = now
    cutoff = datetime.fromtimestamp(now, tz=UTC) - timedelta(
        days=settings.ops_errors_retention_days
    )
    repository.delete_error_events_before(db, cutoff)
