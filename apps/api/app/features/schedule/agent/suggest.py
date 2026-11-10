"""추천 공급: 오늘 호출 한도(`schedule_card`) 안에서 한 묶음 = LLM 한 번 = 같은 created_at 의 제안 최대 5개.

오늘(서버 로컬 날짜) 만든 대기(pending) 제안이 있으면 LLM 을 부르지 않고 섞어서 돌려준다. 없고 호출이 남았으면 새로 만들어 저장한다.
호출이 비었거나 오류면 "나중에"(dismissed) 제안을 대신 보여주고, 호출을 다 썼으면 나중에 제안을 계속 보여주며 전부 확정되면 소진(exhausted)이다.
호출은 공통 관문 `ai_guard.run`(카드 한도)을 거친다. 모델 출력은 믿지 않고 검증한다(길이·종류·날짜 범위·중복). 가족 구성원 이름은 보내지 않는다.
"""

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.ai_assistant.ingest.masking import mask_text
from app.shared import ai_guard
from app.shared.errors import ApiError, bad_request
from app.shared.llm import client as llm

from ..constants import (
    KIND_APPOINTMENT,
    KIND_TODO,
    SUGGESTION_CONFIRMED,
    SUGGESTION_DISMISSED,
    SUGGESTION_PENDING,
)
from ..models import EventSuggestion
from ..service import current_when
from . import chat, prompts, reader, suggest_sources

FEATURE = "schedule_card"
BATCH_SIZE = 5
PAST_DAYS = 14  # 모델에 보내는 일정: 지난 2주
AHEAD_DAYS = 60  # 앞으로 60일(추천 날짜 범위도 같다)
MAX_TITLE = 120
MAX_PLACE = 200


def _local_date(value: datetime) -> date:
    return reader.to_local(value).date()


def _todays(db: Session, user_id: str, group_id: str, today: date) -> list[EventSuggestion]:
    """오늘(로컬 날짜) 만든 내 제안(상태 무관), 만든 순."""
    rows = db.scalars(
        select(EventSuggestion)
        .where(EventSuggestion.user_id == user_id, EventSuggestion.group_id == group_id)
        .order_by(EventSuggestion.created_at, EventSuggestion.start_date, EventSuggestion.id)
    )
    return [s for s in rows if _local_date(s.created_at) == today]


def clean_suggestions(
    data, today: date, taken: set[tuple[str, date]], limit: int = BATCH_SIZE
) -> list[dict]:
    """모델 출력을 검증한다. taken(이미 있는 (제목, 날짜))과 같거나 같은 묶음 안 중복, 범위 밖 날짜는 버린다."""
    items = data.get("suggestions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    last = today + timedelta(days=AHEAD_DAYS)
    seen = set(taken)
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str):
            continue
        title = mask_text(item["title"].strip())[:MAX_TITLE].strip()
        if not title:
            continue
        try:
            day = date.fromisoformat(str(item.get("date", "")).strip())
        except ValueError:
            continue
        if not today <= day <= last or (title, day) in seen:
            continue
        seen.add((title, day))
        place = item.get("place")
        place = mask_text(place.strip())[:MAX_PLACE] if isinstance(place, str) else ""
        kind = item.get("kind")
        out.append(
            {
                "title": title,
                "kind": kind if kind in (KIND_APPOINTMENT, KIND_TODO) else KIND_APPOINTMENT,
                "start_date": day,
                "place": place,
            }
        )
        if len(out) >= limit:
            break
    return out


STATE_OK = "ok"  # 보여줄 추천이 있다
STATE_EXHAUSTED = (
    "exhausted"  # 오늘 호출을 다 썼고 보여줄 것도 없다(전부 확정) — "오늘 추천은 여기까지"
)
STATE_SPENT_EMPTY = "spent_empty"  # 오늘 호출을 다 썼는데 오늘 받은 추천이 하나도 없다 — "일정을 찾지 못했어요" (마무리 인사를 하면 안 됨)
STATE_NO_DATA = "no_data"  # 참고할 데이터가 하나도 없어 AI 를 부르지 않았다
STATE_FILTERED = (
    "filtered"  # 데이터는 있는데 새로 만들 추천이 없다(이미 있는 것과 겹치거나 범위 밖)
)
STATE_PREPARING = "preparing"  # AI 호출이 오류로 끝났다
NO_REFRESH_CODES = ("ai_not_enabled", "llm_unavailable")  # 새로고침해도 풀리지 않는 오류


@dataclass
class Slot:
    """추천 카드 슬롯에 보일 것. can_refresh 는 새로고침이 의미 있는가(오늘 호출이 남았고 오류가 곧 풀릴 수 있는가)."""

    items: list[EventSuggestion]
    state: str
    can_refresh: bool = True


def _pick(made: list[EventSuggestion], status: int, today: date) -> list[EventSuggestion]:
    """오늘 만든 것 중 status 가 같고 날짜가 안 지난 추천을 매번 섞어서 돌려준다."""
    rows = [s for s in made if s.status == status and s.start_date >= today]
    random.shuffle(rows)
    return rows


def _generate(
    db: Session, user_id: str, group_id: str, chat_lines: list[str] | None, now: datetime
) -> list[EventSuggestion] | None:
    """AI 로 새 묶음을 만들어 저장한다. 참고할 데이터가 전혀 없으면 AI 를 부르지 않고 None. 저장할 게 없으면 빈 목록."""
    local_now = now.astimezone(reader.local_tz())
    today = local_now.date()
    data = reader.read(db, group_id, "personal", now, user_id)
    since, until = today - timedelta(days=PAST_DAYS), today + timedelta(days=AHEAD_DAYS)
    nearby = [e for e in data.events if since <= current_when(e)[0] <= until]
    lines = [
        chat.event_line(
            e.id,
            reader.to_local(e.starts_at),
            e.title,
            reader.time_text(e),
            getattr(e, "shared", False),
        )
        for e in nearby
    ]
    sources = suggest_sources.collect(db, user_id, group_id, today, chat_lines)
    if not (lines or sources.requests or sources.family or sources.chat):
        return None
    # 이미 있는 제안(대기·확정·나중에, 날짜 지난 것 포함)은 다시 만들지 않는다
    existing = list(
        db.scalars(
            select(EventSuggestion).where(
                EventSuggestion.user_id == user_id,
                EventSuggestion.group_id == group_id,
                EventSuggestion.status.in_(
                    [SUGGESTION_PENDING, SUGGESTION_CONFIRMED, SUGGESTION_DISMISSED]
                ),
            )
        )
    )
    taken = {(e.title, current_when(e)[0]) for e in data.events}
    taken |= {(s.title, s.start_date) for s in existing}
    prompt = prompts.suggest_prompt(
        local_now,
        lines,
        [mask_text(s.title) for s in existing if s.start_date >= today],
        sources.requests,
        sources.family,
        sources.chat,
    )

    def call():
        response = llm.complete_json(
            prompt,
            prompts.SUGGEST_SCHEMA,
            system=prompts.SUGGEST_SYSTEM,
            max_tokens=2500,  # 입력이 늘고 모델의 생각 토큰이 출력 한도를 같이 써서 JSON 이 잘리지 않게 넉넉히
            model=prompts.SUGGEST_MODEL,
        )
        data = response.data if isinstance(response.data, dict) else {}
        return {"suggestions": data.get("suggestions", [])}, response

    # 묶음마다 달라야 하므로 캐시를 쓰지 않는다. 한도·쿨다운·동의 오류는 그대로 전파한다
    outcome = ai_guard.run(
        db, user_id=user_id, group_id=group_id, feature=FEATURE, cache_key=None, call=call
    )
    items = clean_suggestions(outcome.result, today, taken)
    rows = [EventSuggestion(group_id=group_id, user_id=user_id, created_at=now, **i) for i in items]
    if rows:
        db.add_all(rows)
        db.commit()
    return rows


def supply_slot(
    db: Session,
    user_id: str,
    group_id: str,
    chat_lines: list[str] | None = None,
    *,
    raise_errors: bool = False,
) -> Slot:
    """추천 카드 슬롯 하나를 채운다. 오늘(로컬 날짜) 만든 추천만 본다.
    1) 대기(pending)가 있으면 호출 없이 섞어서 돌려준다.
    2) 오늘 호출이 남았으면 AI 로 새로 만든다. 결과가 비거나 오류면 나중에(dismissed) 추천을 대신 보여주고, 그것도 없으면 상태(state)로 알린다.
    3) 호출을 다 썼으면 나중에 추천을 계속 섞어 보여주고, 그것도 없으면(전부 확정) exhausted.
    raise_errors: 오류를 상태로 바꾸지 않고 그대로 낸다(채팅의 recommend 의도처럼 오류를 따로 다루는 쪽)."""
    now = datetime.now(UTC)
    today = now.astimezone(reader.local_tz()).date()
    made = _todays(db, user_id, group_id, today)
    pending = _pick(made, SUGGESTION_PENDING, today)
    if pending:
        return Slot(pending, STATE_OK)
    later = _pick(made, SUGGESTION_DISMISSED, today)

    def done() -> Slot:
        # 오늘 보여 줄 수 있는 추천을 한 번이라도 받았으면(전부 확정) 마무리 인사, 한 번도 못 받았으면(날짜가 이미 지나 보여 줄 수 없게 된 것만 있는 경우도) 못 찾았다고 알린다
        received = any(s.start_date >= today for s in made)
        return Slot([], STATE_EXHAUSTED if received else STATE_SPENT_EMPTY, False)

    def spent() -> Slot:
        return Slot(later, STATE_OK, False) if later else done()

    if ai_guard.calls_left(db, user_id, group_id, FEATURE) <= 0:
        return spent()
    try:
        rows = _generate(db, user_id, group_id, chat_lines, now)
    except ApiError as e:
        if raise_errors:
            raise
        if e.code.startswith("ai_daily_limit"):
            return spent()
        refresh = e.code not in NO_REFRESH_CODES
        return Slot(later, STATE_OK, refresh) if later else Slot([], STATE_PREPARING, refresh)
    if rows:
        return Slot(sorted(rows, key=lambda r: (r.start_date, r.id)), STATE_OK)
    if later:
        return Slot(later, STATE_OK)
    if rows is None:
        return Slot([], STATE_NO_DATA)
    if ai_guard.calls_left(db, user_id, group_id, FEATURE) <= 0:
        return done()
    return Slot([], STATE_FILTERED)


def supply(
    db: Session, user_id: str, group_id: str, chat_lines: list[str] | None = None
) -> tuple[list[EventSuggestion], bool]:
    """(추천 목록, 오늘 추천 소진 여부). `supply_slot` 과 같되 오류는 그대로 낸다."""
    slot = supply_slot(db, user_id, group_id, chat_lines, raise_errors=True)
    return slot.items, slot.state == STATE_EXHAUSTED


def set_later(
    db: Session, user_id: str, group_id: str, suggestion_id: str, later: bool
) -> EventSuggestion:
    """ "나중에" 표시: later=True 면 나중에(dismissed), False 면 대기(pending)로 되돌린다. 확정된 추천이나 남의 추천은 400."""
    s = db.get(EventSuggestion, suggestion_id)
    if (
        s is None
        or s.user_id != user_id
        or s.group_id != group_id
        or s.status == SUGGESTION_CONFIRMED
    ):
        raise bad_request("invalid_suggestion", "사용할 수 없는 추천이에요")
    s.status = SUGGESTION_DISMISSED if later else SUGGESTION_PENDING
    db.commit()
    return s
