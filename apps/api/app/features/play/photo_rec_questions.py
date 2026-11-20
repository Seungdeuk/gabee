"""사진 추천의 AI 없는 문제: 촬영 월 맞추기, 어느 일정 때 찍었는지 맞추기.

- 월: 촬영 시각(한국 시간)의 월만 묻는다. 촬영 시각이 없으면 올린 날로 대신하지 않고 건너뛴다(오답 방지).
- 일정: 촬영일(한국 시간)과 같은 날의 공동 일정이 정확히 하나일 때만 만든다(부탁에서 생긴 일정·지운 일정은 안 센다).
  제목·장소가 보기 상한(20자)을 넘으면 자르지 않고 그 질문을 건너뛴다.
"""

import random
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.schedule.models import Event
from app.features.schedule.service import current_when

from .service import PHOTO_OPTION_MAX
from .timeutil import aware, local_tz

MONTH_Q = "이 사진은 몇 월에 찍었을까요?"
EVENT_Q = "이 사진은 어느 일정 때 찍었을까요?"
PLACE_Q = "어디서 찍었을까요?"
KIND_MONTH = 1
KIND_EVENT = 2
MAX_OTHERS = 3  # 정답 말고 더할 오답 수


@dataclass(frozen=True)
class PhotoQuestion:
    kind: int
    question: str
    options: list[str]
    answer_index: int
    zoom: int = 8  # 확대 위치는 부른 쪽이 정한다


def _local_day(taken_at: datetime) -> date:
    return aware(taken_at).astimezone(local_tz()).date()


def _build(kind: int, question: str, answer: str, others: list[str], rng: random.Random):
    options = [answer, *others]
    rng.shuffle(options)
    return PhotoQuestion(kind, question, options, options.index(answer))


def month_question(taken_at: datetime | None, rng: random.Random) -> PhotoQuestion | None:
    """촬영 월 문제. 보기는 정답 월 + 다른 월 3개."""
    if taken_at is None:
        return None
    month = _local_day(taken_at).month
    others = rng.sample([m for m in range(1, 13) if m != month], MAX_OTHERS)
    return _build(KIND_MONTH, MONTH_Q, f"{month}월", [f"{m}월" for m in others], rng)


def _shared_events(db: Session, group_id: str) -> list[Event]:
    """공동 일정 원본(지워지지 않은 복사본이 가리키는 것). 부탁에서 생긴 일정은 `origin_id` 가 없어 빠진다."""
    origin_ids = select(Event.origin_id).where(
        Event.group_id == group_id,
        Event.origin_id.is_not(None),
        Event.deleted_at.is_(None),
    )
    return list(
        db.scalars(
            select(Event).where(
                Event.group_id == group_id,
                Event.id.in_(origin_ids),
                Event.deleted_at.is_(None),
            )
        )
    )


def events_on(db: Session, group_id: str, day: date) -> list[Event]:
    """그날의 공동 일정(지운 것 제외)."""
    return [e for e in _shared_events(db, group_id) if current_when(e)[0] == day]


def event_question(
    db: Session, group_id: str, taken_at: datetime | None, rng: random.Random
) -> PhotoQuestion | None:
    """일정 맞추기 문제. 그날 공동 일정이 정확히 하나이고 보기가 2개 이상 나올 때만 만든다."""
    if taken_at is None:
        return None
    day = _local_day(taken_at)
    shared = _shared_events(db, group_id)
    today = [e for e in shared if current_when(e)[0] == day]
    if len(today) != 1:
        return None
    event = today[0]
    others = [e for e in shared if current_when(e)[0] != day]
    modes = [(EVENT_Q, event.title, [e.title for e in others])]
    if event.place:
        modes.append((PLACE_Q, event.place, [e.place for e in others]))
    while modes:  # 종류는 rng 로 고르고, 쓸 수 없으면 다른 종류로 넘어간다
        question, answer, pool = rng.choice(modes)
        modes.remove((question, answer, pool))
        usable = sorted({t for t in pool if t and t != answer and len(t) <= PHOTO_OPTION_MAX})
        if not answer or len(answer) > PHOTO_OPTION_MAX or not usable:
            continue
        picked = rng.sample(usable, min(MAX_OTHERS, len(usable)))
        return _build(KIND_EVENT, question, answer, picked, rng)
    return None
