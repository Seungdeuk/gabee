"""푸시 알림: 받는 사람 계산(차단 규칙)과 발송.

알림함 사건은 `app/shared/notifications.py` 의 `notify()` 가, 알림함에 남기지 않는 푸시는 `push_only()` 가 부른다.
문구는 부르는 쪽이 정한다 — 알림함 사건은 고정 템플릿 제목만 쓴다. 토큰은 로그에 남기지 않는다."""

import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time
from typing import Any, NotRequired, TypedDict
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.push_models import PushSetting, PushToken

logger = logging.getLogger(__name__)

EXPO_SEND_URL = "https://exp.host/--/api/v2/push/send"
ANDROID_CHANNEL_ID = "default"
_BATCH = 100  # Expo 가 한 번에 받는 최대 개수
_TIMEOUT_SECONDS = 5
_PENDING_KEY = "pending_push"
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="push")

# 방해금지 시간은 이 시간대로 본다(앱 사용자가 모두 한국 시간대라는 가정).
_TZ = ZoneInfo("Asia/Seoul")


class PushPlan(TypedDict):
    """기기 하나에 보낼 푸시 한 건."""

    user_id: str
    token: str
    title: str
    body: str | None
    data: dict[str, Any]
    collapse_key: NotRequired[
        str
    ]  # 있으면 같은 키의 알림을 한 건으로 교체(안드로이드 tag, iOS collapseId)


def in_quiet_hours(now: datetime, start: time | None, end: time | None) -> bool:
    """now(UTC 등 시간대가 있는 시각)가 방해금지 [start, end) 안인지. 자정을 넘기는 구간(22:00~07:00)도 본다."""
    if start is None or end is None:
        return False
    local = now.astimezone(_TZ).time().replace(tzinfo=None)
    if start <= end:
        return start <= local < end
    return local >= start or local < end


def plan_recipients(
    db: Session,
    *,
    user_ids: Iterable[str],
    kind: str,
    title: str,
    body: str | None,
    data: dict[str, Any],
    now: datetime,
    collapse_key: str | None = None,
) -> list[PushPlan]:
    """받는 사람마다 설정을 적용해 보낼 푸시 목록을 만든다.

    푸시를 껐거나(`enabled`) 이 분류를 껐거나(`muted_kinds`) 방해금지 시간이면 그 사람은 뺀다.
    남은 사람은 기기(토큰)마다 한 건씩, 같은 (사용자, 토큰)은 한 번만."""
    wanted = list(dict.fromkeys(user_ids))
    if not wanted:
        return []
    settings = {
        s.user_id: s for s in db.scalars(select(PushSetting).where(PushSetting.user_id.in_(wanted)))
    }
    allowed = []
    for uid in wanted:
        setting = settings.get(uid)  # 줄이 없으면 기본값(켬, 끈 분류 없음, 방해금지 없음)
        if setting is not None and (
            not setting.enabled
            or kind in (setting.muted_kinds or [])
            or in_quiet_hours(now, setting.quiet_start, setting.quiet_end)
        ):
            continue
        allowed.append(uid)
    if not allowed:
        return []
    tokens = db.scalars(
        select(PushToken)
        .where(PushToken.user_id.in_(allowed))
        .order_by(PushToken.created_at, PushToken.id)
    )
    seen: set[tuple[str, str]] = set()
    plans: list[PushPlan] = []
    for row in tokens:
        key = (row.user_id, row.token)
        if key in seen:
            continue
        seen.add(key)
        plan = PushPlan(user_id=row.user_id, token=row.token, title=title, body=body, data=data)
        if collapse_key:
            plan["collapse_key"] = collapse_key
        plans.append(plan)
    return plans


def queue_push(
    db: Session,
    *,
    user_ids: Iterable[str],
    kind: str,
    title: str,
    body: str | None,
    data: dict[str, Any],
    collapse_key: str | None = None,
) -> None:
    """이 세션이 커밋되면 보낼 푸시를 쌓아 둔다(차단 규칙은 발송 직전에 적용). 꺼져 있으면 아무것도 하지 않는다."""
    if not settings.push_enabled:
        return
    db.info.setdefault(_PENDING_KEY, []).append(
        {
            "user_ids": list(user_ids),
            "kind": kind,
            "title": title,
            "body": body,
            "data": data,
            "collapse_key": collapse_key,
        }
    )


def push_only(
    db: Session,
    *,
    user_ids: Iterable[str],
    kind: str,
    title: str,
    body: str | None,
    data: dict[str, Any],
    collapse_key: str | None = None,
) -> None:
    """알림함에 남기지 않고 푸시만 보낸다(소통 메시지처럼 알림함에서 제외하는 사건). 커밋 뒤에 발송한다.
    collapse_key 가 있으면 같은 키의 알림이 잠금 화면에서 한 건으로 교체된다."""
    queue_push(
        db,
        user_ids=user_ids,
        kind=kind,
        title=title,
        body=body,
        data=data,
        collapse_key=collapse_key,
    )


def _submit(fn, *args) -> None:
    """발송을 백그라운드 스레드에서 실행한다(시험은 이 함수를 그 자리 실행으로 바꾼다)."""
    _executor.submit(fn, *args)


def _now() -> datetime:
    """발송 시점의 현재 시각(방해금지 판단에 쓴다). 시험은 이 함수를 고정 시각으로 바꿔 실제 시각에 따라 결과가 달라지지 않게 한다."""
    return datetime.now(UTC)


def _post(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Expo 푸시 API 에 한 묶음을 보내고 JSON 응답을 돌려준다(시험은 이 함수를 바꾼다)."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if settings.push_expo_access_token:
        headers["Authorization"] = f"Bearer {settings.push_expo_access_token}"
    response = httpx.post(EXPO_SEND_URL, json=messages, headers=headers, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _message(plan: PushPlan) -> dict[str, Any]:
    message: dict[str, Any] = {
        "to": plan["token"],
        "title": plan["title"],
        "data": plan["data"],
        "channelId": ANDROID_CHANNEL_ID,
        "priority": "high",
        "sound": "default",
    }
    if plan["body"] is not None:
        message["body"] = plan["body"]
    if plan.get("collapse_key"):
        message["tag"] = plan["collapse_key"]  # 안드로이드: 같은 tag 의 알림을 교체
        message["collapseId"] = plan["collapse_key"]  # iOS: 같은 collapseId 의 알림을 교체
    return message


def _deliver(items: list[dict[str, Any]]) -> None:
    """쌓인 푸시를 실제로 보낸다. 어떤 오류도 밖으로 내지 않는다(로그에는 예외 종류만, 토큰·문구는 남기지 않는다)."""
    try:
        now = _now()
        with SessionLocal() as db:
            plans: list[PushPlan] = []
            for item in items:
                plans += plan_recipients(db, now=now, **item)
        for start in range(0, len(plans), _BATCH):
            chunk = plans[start : start + _BATCH]
            _send_chunk(chunk)
    except Exception as exc:
        logger.warning("push deliver failed error=%s", type(exc).__name__)


def _send_chunk(chunk: list[PushPlan]) -> None:
    try:
        result = _post([_message(p) for p in chunk])
        tickets = result["data"]
        if len(tickets) != len(chunk):
            raise ValueError("ticket count mismatch")
    except Exception as exc:
        logger.warning("push send failed error=%s", type(exc).__name__)
        return
    dead = [
        plan["token"]
        for plan, ticket in zip(chunk, tickets, strict=True)
        if isinstance(ticket, dict)
        and ticket.get("status") == "error"
        and (ticket.get("details") or {}).get("error") == "DeviceNotRegistered"
    ]
    if dead:
        with SessionLocal() as db:
            db.execute(delete(PushToken).where(PushToken.token.in_(dead)))
            db.commit()


@event.listens_for(Session, "after_commit")
def _send_after_commit(session: Session) -> None:
    # 저장점(begin_nested)이 닫힐 때도 이 이벤트가 온다. 저장점 안에서 온 이벤트(in_nested_transaction)는 진짜 커밋이 아니다.
    if session.in_nested_transaction():
        return
    pending = session.info.pop(_PENDING_KEY, None)
    if pending:
        _submit(_deliver, pending)


@event.listens_for(Session, "after_rollback")
def _drop_after_rollback(session: Session) -> None:
    # 저장점만 롤백된 경우(in_nested_transaction)에는 쌓아 둔 푸시를 지우지 않는다.
    if session.in_nested_transaction():
        return
    session.info.pop(_PENDING_KEY, None)
