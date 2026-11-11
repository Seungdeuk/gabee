"""예약 푸시(2026-11-11 규칙): 약속·할 일 모두 **시간이 있으면 시작 30분 전**, **시간이 없으면(종일 포함) 전날 저녁 9시에 한 번**(한국 시간).

예약 목록을 따로 만들지 않고, 서버가 1분마다 알릴 항목을 직접 찾아 보낸다. 그래서 일정을 고치거나 지워도
예약을 고칠 필요가 없고(다음 확인 때 현재 값이 쓰인다), 같은 푸시가 두 번 가지 않게 `scheduled_push_log` 의 고유 키를 먼저 선점한 쪽만 보낸다
(서버가 여러 대여도 안전하다). 문구는 고정이라 일정·할 일의 제목·장소를 싣지 않는다. 푸시 설정(끔·분류 끔·방해금지)은 `push_only` 가 적용한다.
`PUSH_ENABLED` 가 꺼져 있으면 아무것도 하지 않는다.

- 시간이 있는 항목: 시작 30분 전(포함)~시작 전(미포함). 약속은 `event:<id>:<시작 시각>`, 할 일은 `todo:<id>:<시작 시각>` 키.
- 시간이 없는 항목(시간 칸이 비었거나 종일 00:00~23:59): **내일** 날짜인 항목을 오늘 저녁 9시부터 자정 전까지 알린다. 키 `evening:<id>:<날짜>`.
  저녁 9시 이후에 만든 항목은 알리지 않는다(방금 만든 것을 곧바로 알리면 소음). 오늘 날짜의 시간 없는 항목은 전날이 없으니 알리지 않는다.
- 이전의 "할 일 당일 오전 9시" 알림은 없앴다."""

import logging
import threading
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.family_group.models import GroupMember
from app.shared.config import settings
from app.shared.db import SessionLocal
from app.shared.push import plan_recipients, push_only
from app.shared.push_models import ScheduledPushLog

from .constants import KIND_APPOINTMENT, KIND_TODO
from .models import Event
from .timeutil import local_tz

logger = logging.getLogger(__name__)

TICK_SECONDS = 60  # 확인 주기
EVENT_LEAD = timedelta(minutes=30)  # 시간이 있는 항목은 시작 이만큼 전부터 보낸다
EVENING_HOUR = 21  # 시간이 없는 항목은 전날 이 시각(한국 시간)부터 자정 전까지 한 번 알린다

EVENT_TITLE = "30분 안에 시작하는 일정이 있어요"
TODO_SOON_TITLE = "30분 뒤에 챙길 할 일이 있어요"
EVENING_TITLE = "내일 챙길 일정이 있어요"

_started = threading.Event()

# 종일 일정은 앱이 00:00~23:59 로 저장한다(시간 칸이 비어 있지 않다). 시작 시각만 보면 전날 23:30 에 "30분 안에 시작" 푸시가 가므로 뺀다.
_ALL_DAY = and_(Event.start_time == time(0, 0), Event.end_time == time(23, 59))
# 시간이 없는 항목: 시간 칸이 비었거나 종일. 시간이 있는 항목은 그 반대
_NO_TIME = or_(Event.start_time.is_(None), _ALL_DAY)
# 지금도 이 가족인 사람의 일정만(가족을 나가도 일정 줄은 남는다)
_STILL_MEMBER = exists().where(
    GroupMember.group_id == Event.group_id, GroupMember.user_id == Event.user_id
)


def _claim(db: Session, key: str, user_id: str) -> bool:
    """이 푸시를 보내겠다고 선점한다. 이미 보냈거나 다른 서버가 먼저 선점했으면 False."""
    try:
        with db.begin_nested():
            db.add(ScheduledPushLog(key=key, user_id=user_id))
        return True
    except IntegrityError:
        return False


def _due_soon(db: Session, now: datetime, kind: int, prefix: str) -> list[tuple[str, str]]:
    """지금 30분 전 구간에 들어온 시간 있는 항목(약속이면 kind=1, 할 일이면 kind=2)의 (id 와 시작 시각으로 만든 키, 주인 id). 시간이 없는 항목은 뺀다."""
    tz = local_tz()
    local = now.astimezone(tz)
    rows = db.execute(
        select(Event.id, Event.user_id, Event.start_date, Event.start_time)
        .where(
            Event.kind == kind,
            Event.deleted_at.is_(None),
            Event.user_id.is_not(None),
            Event.checked.is_(False),  # 이미 한 약속은 알리지 않는다
            Event.start_date.in_({local.date(), (local + EVENT_LEAD).date()}),
            Event.start_time.is_not(None),
            ~_ALL_DAY,
            _STILL_MEMBER,
        )
        .order_by(Event.id)  # 서버가 여러 대여도 같은 순서로 선점해 교착을 피한다
    )
    out = []
    for event_id, user_id, start_date, start_time in rows:
        start = datetime.combine(start_date, start_time, tzinfo=tz)
        if start - EVENT_LEAD <= now < start:
            out.append(
                (f"{prefix}:{event_id}:{start.isoformat()}", user_id)
            )  # 시작 시각이 바뀌면 키도 바뀐다
    return out


def _due_evening(db: Session, now: datetime) -> list[tuple[str, str]]:
    """내일 날짜인 시간 없는 항목(약속·할 일)의 (id 와 날짜로 만든 키, 주인 id). 오늘 저녁 9시 전에는 없다.
    저녁 9시 전에 만들어 둔 것만 보낸다(밤 10시에 방금 만든 "내일" 항목을 곧바로 알리면 소음이다)."""
    tz = local_tz()
    local = now.astimezone(tz)
    if local.time() < time(EVENING_HOUR, 0):
        return []
    tomorrow = local.date() + timedelta(days=1)
    # created_at 은 UTC 로 저장된다. SQLite 는 시간대를 버리고 숫자만 비교하므로 같은 UTC 기준으로 맞춘다(PostgreSQL 은 어느 쪽이든 같은 순간)
    evening = datetime.combine(local.date(), time(EVENING_HOUR, 0), tzinfo=tz).astimezone(UTC)
    rows = db.execute(
        select(Event.id, Event.user_id)
        .where(
            Event.kind.in_((KIND_APPOINTMENT, KIND_TODO)),
            Event.deleted_at.is_(None),
            Event.user_id.is_not(None),
            Event.checked.is_(False),
            Event.start_date == tomorrow,
            _NO_TIME,
            Event.created_at < evening,
            _STILL_MEMBER,
        )
        .order_by(Event.id)
    )
    return [(f"evening:{event_id}:{tomorrow.isoformat()}", user_id) for event_id, user_id in rows]


def _send(db: Session, claimed: dict[str, int], title: str, event: str) -> None:
    """선점에 성공한 사람마다 푸시를 한 번(여러 건이어도 한 번)만 쌓는다. 푸시 설정은 push_only 가 적용한다."""
    for user_id in claimed:
        push_only(
            db,
            user_ids=[user_id],
            kind="schedule",
            title=title,
            body=None,
            data={"kind": "schedule", "event": event},
            collapse_key=f"{event}:{user_id}",
        )


def run_due(db: Session, now: datetime | None = None) -> int:
    """지금 보낼 예약 푸시를 찾아 보낸다. 선점(기록)한 항목 수를 돌려준다. 푸시가 꺼져 있으면 아무것도 하지 않는다."""
    if not settings.push_enabled:
        return 0
    now = now or datetime.now(UTC)
    total = 0
    for due, title, event in (
        (_due_soon(db, now, KIND_APPOINTMENT, "event"), EVENT_TITLE, "event_soon"),
        (_due_soon(db, now, KIND_TODO, "todo"), TODO_SOON_TITLE, "todo_soon"),
        (_due_evening(db, now), EVENING_TITLE, "evening_before"),
    ):
        claimed: dict[str, int] = defaultdict(int)
        receivable: dict[str, bool] = {}
        for key, user_id in due:
            if user_id not in receivable:
                # 푸시를 껐거나 방해금지·토큰 없음으로 지금 못 받는 사람은 기록(선점)하지 않는다 — 방해금지가 끝난 뒤 다음 확인에서 보낸다
                receivable[user_id] = bool(
                    plan_recipients(
                        db,
                        user_ids=[user_id],
                        kind="schedule",
                        title=title,
                        body=None,
                        data={},
                        now=now,
                    )
                )
            if receivable[user_id] and _claim(db, key, user_id):
                claimed[user_id] += 1
        if claimed:
            _send(db, claimed, title, event)
            db.commit()  # 선점 기록을 저장하고(커밋 뒤에 푸시가 나간다)
            total += sum(claimed.values())
    return total


def tick() -> None:
    """한 번 확인한다. 어떤 오류도 밖으로 내지 않는다(주기 작업이 멈추지 않게, 로그에는 종류만)."""
    try:
        with SessionLocal() as db:
            run_due(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("push schedule tick failed error=%s", type(exc).__name__)


def _loop() -> None:
    while True:
        tick()
        threading.Event().wait(TICK_SECONDS)


def start() -> None:
    """서버가 시작할 때 부른다: 푸시가 켜져 있으면 1분마다 확인하는 백그라운드 스레드를 한 번만 띄운다."""
    if not settings.push_enabled or _started.is_set():
        return
    _started.set()
    threading.Thread(target=_loop, name="push-schedule", daemon=True).start()
