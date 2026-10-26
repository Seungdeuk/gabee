"""에이전트가 읽는 데이터. 호출한 채팅 종류(channel)에 따라 읽을 수 있는 범위가 달라진다.

서버에서는 과거 1년·미래 1년까지 조회하고, LLM 에는 지금과 가까운 것부터 일정 수만큼만 보낸다(`select_for_prompt`).
정산·돌봄·채팅은 아직 연결하지 않았다 — 연결하면 `read` 의 해당 항목을 채운다.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.schedule import repository as schedule_repo
from app.features.schedule.models import Event
from app.features.schedule.timeutil import local_tz

from .period import Period
from .schemas import Channel

SOURCES_BY_CHANNEL: dict[str, tuple[str, ...]] = {
    "personal": ("schedule", "billing", "care", "personal_chat", "family_chat"),
    # 가족 채팅에서 호출되면 개인 채팅은 읽지 않는다(개인 대화가 가족 앞에 나오지 않게)
    "family": ("schedule", "billing", "care", "family_chat"),
}

READ_SPAN = timedelta(days=365)  # 과거·미래 각각 1년
PROMPT_EVENT_LIMIT = 150  # LLM 에 보내는 일정 수 상한(넘으면 지금과 가까운 순)
# 서버에서는 과거·미래 1년을 읽고, LLM 에는 문장의 기간에 맞는 일정(기간이 없으면 가까운 순 상한)만 id·날짜·제목으로 보낸다


def allowed_sources(channel: Channel) -> tuple[str, ...]:
    return SOURCES_BY_CHANNEL[channel]


@dataclass
class AgentData:
    sources: tuple[str, ...]
    events: list[Event] = field(default_factory=list)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def read(
    db: Session,
    group_id: str,
    channel: Channel,
    now: datetime | None = None,
    user_id: str | None = None,
) -> AgentData:
    """user_id 를 주면 그 사람의 일정(과 주인이 없던 옛 일정)만 읽는다. 에이전트는 항상 호출한 사람 몫만 본다."""
    now = now or datetime.now(UTC)
    sources = allowed_sources(channel)
    data = AgentData(sources=sources)
    if "schedule" in sources:
        since = now - READ_SPAN
        until = now + READ_SPAN
        data.events = [
            e
            for e in schedule_repo.list_from(db, group_id, since, user_id)
            if aware(e.starts_at) <= until
        ]
    return data


def to_local(value: datetime) -> datetime:
    return aware(value).astimezone(local_tz())


def select_for_prompt(
    events: list[Event], now: datetime, period: Period | None, limit: int = PROMPT_EVENT_LIMIT
) -> tuple[list[Event], int]:
    """(LLM 에 보낼 일정, 생략한 수). 문장에서 기간을 뽑았으면 그 기간(앞뒤 하루 여유)의 일정만,
    못 뽑았으면 읽은 전체에서 지금과 가까운 순으로 보낸다. 어느 쪽이든 limit 개를 넘으면 가까운 순으로 자르고 날짜순으로 돌려준다."""
    pool = events
    if period is not None:
        wide = period.widened()
        pool = [e for e in events if wide.start <= to_local(e.starts_at).date() <= wide.end]
    if len(pool) <= limit:
        return sorted(pool, key=lambda e: aware(e.starts_at)), 0
    nearest = sorted(pool, key=lambda e: abs(aware(e.starts_at) - now))[:limit]
    return sorted(nearest, key=lambda e: aware(e.starts_at)), len(pool) - limit


def select_by_model(
    events: list[Event],
    now: datetime,
    period: Period | None,
    keyword: str,
    limit: int = PROMPT_EVENT_LIMIT,
) -> tuple[list[Event], int]:
    """모델이 되돌려준 기간·제목 키워드로, 이미 읽어 둔 일정 안에서만 거른다(DB 를 다시 조회하지 않는다).
    둘 다 없으면 가까운 순으로 보낸다."""
    pool = events
    if period is not None:
        wide = period.widened()
        pool = [e for e in pool if wide.start <= to_local(e.starts_at).date() <= wide.end]
    needle = "".join(keyword.split()).lower()
    if needle:
        pool = [e for e in pool if needle in "".join(e.title.split()).lower()]
    return select_for_prompt(pool, now, None, limit)
