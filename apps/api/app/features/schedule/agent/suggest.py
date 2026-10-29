"""추천 공급: 하루 최대 3묶음(한 묶음 = LLM 한 번 = 같은 created_at 의 제안 최대 5개).

오늘(서버 로컬 날짜) 만든 대기 제안이 있으면 LLM 을 부르지 않고 그것을 돌려준다. 없고 오늘 3묶음을 다 만들었으면 소진(exhausted)이다.
그 밖이면 LLM 으로 새로 만들어 저장한다. 호출은 공통 관문 `ai_guard.run`(카드 한도)을 거치고, 한도·동의 오류는 그대로 전파한다.
모델 출력은 믿지 않고 검증한다(길이·종류·날짜 범위·중복). 가족 구성원 이름은 보내지 않는다.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.ai_assistant.ingest.masking import mask_text
from app.shared import ai_guard
from app.shared.llm import client as llm

from ..constants import (
    KIND_APPOINTMENT,
    KIND_TODO,
    SUGGESTION_CONFIRMED,
    SUGGESTION_PENDING,
)
from ..models import EventSuggestion
from ..service import current_when
from . import chat, prompts, reader, suggest_sources

FEATURE = "schedule_card"
BATCH_SIZE = 5
MAX_BATCHES_PER_DAY = 3
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


def supply(
    db: Session, user_id: str, group_id: str, chat_lines: list[str] | None = None
) -> tuple[list[EventSuggestion], bool]:
    """(대기 제안 목록, 오늘 추천 소진 여부). 대기 제안이 있으면 LLM 을 부르지 않는다.
    chat_lines: 앱이 보낸 개인 AI 채팅의 최근 내 말(저장하지 않고 이번 생성에만 쓴다)."""
    now = datetime.now(UTC)
    local_now = now.astimezone(reader.local_tz())
    today = local_now.date()
    made = _todays(db, user_id, group_id, today)
    pending = [s for s in made if s.status == SUGGESTION_PENDING]
    if pending:
        return pending, False
    if len({s.created_at for s in made}) >= MAX_BATCHES_PER_DAY:
        return [], True

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
    # 이미 있는 제안(대기·확정, 날짜 지난 것 포함)은 다시 만들지 않는다
    existing = list(
        db.scalars(
            select(EventSuggestion).where(
                EventSuggestion.user_id == user_id,
                EventSuggestion.group_id == group_id,
                EventSuggestion.status.in_([SUGGESTION_PENDING, SUGGESTION_CONFIRMED]),
            )
        )
    )
    taken = {(e.title, current_when(e)[0]) for e in data.events}
    taken |= {(s.title, s.start_date) for s in existing}
    sources = suggest_sources.collect(db, user_id, group_id, today, chat_lines)
    prompt = prompts.suggest_prompt(
        local_now,
        lines,
        [mask_text(s.title) for s in existing if s.start_date >= today],
        sources.requests,
        sources.billing,
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
    # 다시 불러올 때와 같은 순서(날짜 빠른 순)로 돌려준다
    return sorted(rows, key=lambda r: (r.start_date, r.id)), False
