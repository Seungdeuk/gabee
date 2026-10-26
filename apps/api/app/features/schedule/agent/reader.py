"""에이전트가 읽는 데이터. 호출한 채팅 종류(channel)에 따라 읽을 수 있는 범위가 달라진다.

서버에서는 과거 1년·미래 1년까지 조회하고, LLM 에는 질문에 해당하는 구간만 보낸다(`window`).
정산·돌봄·채팅은 아직 연결하지 않았다 — 연결하면 `read` 의 해당 항목을 채운다.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.features.schedule import repository as schedule_repo
from app.features.schedule.models import Event

from .schemas import Channel

SOURCES_BY_CHANNEL: dict[str, tuple[str, ...]] = {
    "personal": ("schedule", "billing", "care", "personal_chat", "family_chat"),
    # 가족 채팅에서 호출되면 개인 채팅은 읽지 않는다(개인 대화가 가족 앞에 나오지 않게)
    "family": ("schedule", "billing", "care", "family_chat"),
}

READ_SPAN = timedelta(days=365)  # 과거·미래 각각 1년


def allowed_sources(channel: Channel) -> tuple[str, ...]:
    return SOURCES_BY_CHANNEL[channel]


@dataclass
class AgentData:
    sources: tuple[str, ...]
    events: list[Event] = field(default_factory=list)


def read(db: Session, group_id: str, channel: Channel, now: datetime | None = None) -> AgentData:
    now = now or datetime.now(UTC)
    sources = allowed_sources(channel)
    data = AgentData(sources=sources)
    if "schedule" in sources:
        since = now - READ_SPAN
        until = now + READ_SPAN
        data.events = [
            e for e in schedule_repo.list_from(db, group_id, since) if _aware(e.starts_at) <= until
        ]
    return data


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def window(events: list[Event], start: datetime, end: datetime) -> list[Event]:
    """질문에 해당하는 구간(start 이상, end 미만)만 골라 LLM 에 보낼 양을 줄인다."""
    return [e for e in events if start <= _aware(e.starts_at) < end]
