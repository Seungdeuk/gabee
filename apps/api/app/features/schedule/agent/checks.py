"""에이전트 체크. "치과 확인했어", "세탁물 다 했어"처럼 말하면 확인·완료로 표시하고, "확인 안 한 일정 보여줘"에는 아직 체크하지
않은 일정을 찾아 보여 준다.

체크는 되돌릴 수 있는 가벼운 동작이라 수정·삭제처럼 확인 카드를 거치지 않고 바로 실행한다(요청이 곧 승인). 대상은 모델이 일정
목록의 id 로 고르고, 체크는 각자 자기 줄에서 한다(`service.set_checked`). 확인하지 않은 일정을 찾는 일에는 LLM 을 쓰지 않는다.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.features.schedule import service
from app.features.schedule.models import Event

from . import reader
from .period import Period
from .schemas import AgentResponse, Card

MAX_CHECKED = 20  # 한 번에 표시할 수 있는 일정 수
MAX_LISTED = 20  # 한 번에 보여 주는 확인하지 않은 일정 수
NOT_FOUND_TEXT = "어떤 일정인지 찾지 못했어요. 일정 이름이나 날짜를 함께 알려 주세요"

KIND_APPOINTMENT = 1


def _done_text(event: Event) -> str:
    """약속의 체크는 '확인했어요', 할 일의 체크는 '완료했어요'."""
    return "확인했어요" if event.kind == KIND_APPOINTMENT else "완료했어요"


def _undo_text(event: Event) -> str:
    return "확인을 취소했어요" if event.kind == KIND_APPOINTMENT else "완료를 취소했어요"


def _day(event: Event) -> date:
    return reader.to_local(event.starts_at).date()


def _card(events: list[Event]) -> list[Card]:
    return [Card(type="event_list", data={"events": [reader.brief(e) for e in events]})]


def _mark(
    db: Session,
    user_id: str,
    group_id: str,
    event_ids: list[str],
    by_id: dict[str, Event],
    done: bool,
) -> AgentResponse:
    picked = [by_id[i] for i in event_ids if i in by_id][:MAX_CHECKED]
    if not picked:
        return AgentResponse(intent="check", text=NOT_FOUND_TEXT)
    lines = []
    updated = []
    for event in picked:
        saved = service.set_checked(db, group_id, user_id, event.id, done)
        updated.append(saved)
        lines.append(f"'{saved.title}' {_done_text(saved) if done else _undo_text(saved)}")
    return AgentResponse(intent="check", text="\n".join(lines), cards=_card(updated))


def _unchecked(all_events: list[Event], period: Period | None, today: date) -> AgentResponse:
    start, end = (period.start, period.end) if period else (today, today)
    found = sorted(
        (e for e in all_events if not e.checked and start <= _day(e) <= end),
        key=lambda e: e.starts_at,
    )
    when = f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}" if period else "오늘"
    if not found:
        return AgentResponse(intent="check", text=f"{when} 확인하지 않은 일정이 없어요")
    shown = found[:MAX_LISTED]
    more = len(found) - len(shown)
    text = f"{when} 아직 확인하지 않은 일정이 {len(found)}개 있어요"
    if more:
        text += f" (가까운 {len(shown)}개만 보여 드려요)"
    return AgentResponse(intent="check", text=text, cards=_card(shown))


def respond(
    db: Session,
    user_id: str,
    group_id: str,
    action: str,
    event_ids: list[str],
    by_id: dict[str, Event],
    all_events: list[Event],
    period: Period | None,
    today: date,
) -> AgentResponse:
    """action: mark(확인·완료로 표시) / unmark(표시 취소) / list(확인하지 않은 일정 보기). 모델이 action 을 비우면
    대상이 있으면 mark, 없으면 list 로 본다."""
    if action not in ("mark", "unmark", "list"):
        action = "mark" if event_ids else "list"
    if action == "list":
        return _unchecked(all_events, period, today)
    return _mark(db, user_id, group_id, event_ids, by_id, action == "mark")
