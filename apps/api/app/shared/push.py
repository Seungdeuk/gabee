"""푸시 알림: 받는 사람 계산(차단 규칙)과 발송.

알림함 사건은 `app/shared/notifications.py` 의 `notify()` 가, 알림함에 남기지 않는 푸시는 `push_only()` 가 부른다.
문구는 부르는 쪽이 정한다 — 알림함 사건은 고정 템플릿 제목만 쓴다. 토큰은 로그에 남기지 않는다."""

from collections.abc import Iterable
from datetime import datetime, time
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.push_models import PushSetting, PushToken

# 방해금지 시간은 이 시간대로 본다(앱 사용자가 모두 한국 시간대라는 가정).
_TZ = ZoneInfo("Asia/Seoul")


class PushPlan(TypedDict):
    """기기 하나에 보낼 푸시 한 건."""

    user_id: str
    token: str
    title: str
    body: str | None
    data: dict[str, Any]


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
        plans.append(
            PushPlan(user_id=row.user_id, token=row.token, title=title, body=body, data=data)
        )
    return plans
