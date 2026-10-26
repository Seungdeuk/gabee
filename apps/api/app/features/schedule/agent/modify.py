"""에이전트 수정·삭제. 모델이 고른 대상 일정과 바뀔 값을 코드가 검증해 확인 카드로 보여 주고, 사용자가 확인하면
처음부터 다시 검증해서 실행한다(`service.update`·`service.remove`).

- 대상은 모델이 일정 목록의 id 만 고른다. 같은 이름이 여럿이면 모델이 지금과 가장 가까운 하나를 고르고, 확인 카드에 날짜가
  보이니 틀리면 사용자가 취소한다. 목록에 없는 id 는 버린다.
- 내 줄만 고치고 지운다(`service.owns`). 복사본은 독립이라 원본을 고치거나 지워도 공유받은 사람의 일정은 그대로다.
- 확인 요청의 내용은 앱이 돌려준 것이므로 믿지 않는다: 일정을 다시 찾고, 소유자를 다시 확인하고, 값을 다시 검증한다.
"""

from datetime import date, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.features.schedule import service
from app.features.schedule.models import Event
from app.features.schedule.schemas import EventUpdate
from app.shared.errors import ApiError, bad_request

from . import reader, register
from .schemas import AgentResponse, Card, PendingAction

TITLE_MAX = 120
PLACE_MAX = 200
MEMO_MAX = 1000
CLEARABLE = ("time", "place", "memo")
# 확인 요청에서 받는 바꿀 값의 이름(EventUpdate 의 필드). 그 밖의 이름은 버린다
UPDATE_KEYS = ("title", "start_date", "start_time", "end_time", "kind", "place", "memo")
WEEKDAYS = "월화수목금토일"
KIND_NAMES = {1: "약속", 2: "할 일"}

NOT_FOUND_TEXT = "어떤 일정인지 찾지 못했어요. 일정 이름이나 날짜를 함께 알려 주세요"
NOT_OWNER_EDIT = "내 일정만 고칠 수 있어요"
NOT_OWNER_DELETE = "내 일정만 지울 수 있어요"
NOTHING_TEXT = "바꿀 내용을 찾지 못했어요. 무엇을 어떻게 바꿀지 알려 주세요"


def _text(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def clean_changes(raw) -> dict:
    """모델이 돌려준 changes 를 검증한다. 형식이 틀린 값은 빈 값(바꾸지 않음)으로 둔다."""
    if not isinstance(raw, dict):
        raw = {}
    clear = raw.get("clear")
    clear = (
        [c for c in clear if isinstance(c, str) and c in CLEARABLE]
        if isinstance(clear, list)
        else []
    )
    kind = raw.get("kind")
    return {
        "title": _text(raw.get("title"), TITLE_MAX),
        "date": _text(raw.get("date"), 10),
        "start_time": _text(raw.get("start_time"), 5),
        "end_time": _text(raw.get("end_time"), 5),
        "kind": kind if kind in (1, 2) and not isinstance(kind, bool) else 0,
        "place": _text(raw.get("place"), PLACE_MAX),
        "memo": _text(raw.get("memo"), MEMO_MAX),
        "clear": list(dict.fromkeys(clear)),
    }


def _end_for(start: str, event: Event) -> str:
    """시작만 바꿨을 때의 끝 시간: 원래 길이를 유지하고, 원래 끝 시간이 없었으면 1시간 뒤."""
    _, old_start, old_end = service.current_when(event)
    if old_start and old_end:
        minutes = (
            datetime.combine(date.min, old_end) - datetime.combine(date.min, old_start)
        ).seconds // 60
        if minutes > 0:
            begin = datetime.strptime(start, "%H:%M")
            end = begin + timedelta(minutes=minutes)
            return "23:59" if end.day != begin.day else end.strftime("%H:%M")
    return register.plus_hour(start)


def build_update(changes: dict, event: Event, now: date) -> dict:
    """모델이 읽은 값을 EventUpdate 에 넣을 값(문자열)으로 바꾼다. 형식·범위가 틀린 값은 버린다."""
    out: dict = {}
    if changes["title"]:
        out["title"] = changes["title"]
    new_date = register.valid_date(changes["date"], now)
    if new_date:
        out["start_date"] = new_date
    if changes["kind"]:
        out["kind"] = changes["kind"]
    for field in ("place", "memo"):
        if changes[field]:
            out[field] = changes[field]
        elif field in changes["clear"]:
            out[field] = ""
    start = register.valid_time(changes["start_time"])
    end = register.valid_time(changes["end_time"])
    if start:
        out["start_time"] = start
        out["end_time"] = end if end and end > start else _end_for(start, event)
    elif end:
        out["end_time"] = end
    elif "time" in changes["clear"]:
        out["start_time"] = None
        out["end_time"] = None
    return out


def _day_text(value: date) -> str:
    return f"{value.month}월 {value.day}일({WEEKDAYS[value.weekday()]})"


def _when_text(start, end) -> str:
    if start and end:
        return f"{start:%H:%M}~{end:%H:%M}"
    return f"{start:%H:%M}" if start else "시간 없음"


def _diff(event: Event, body: EventUpdate, after) -> list[dict]:
    """바뀌는 항목만 '이전 → 새 값'으로. after 는 고친 뒤의 (날짜, 시작, 끝)."""
    lines: list[dict] = []

    def add(label: str, before: str, now: str) -> None:
        if before != now:
            lines.append({"label": label, "before": before, "after": now})

    if body.title is not None:
        add("제목", event.title, body.title.strip())
    before_date, before_start, before_end = service.current_when(event)
    add("날짜", _day_text(before_date), _day_text(after[0]))
    add("시간", _when_text(before_start, before_end), _when_text(after[1], after[2]))
    if body.place is not None:
        add("장소", event.place or "없음", body.place.strip() or "없음")
    if body.memo is not None:
        add("메모", event.memo or "없음", body.memo or "없음")
    if body.kind is not None:
        add("형태", KIND_NAMES.get(event.kind, ""), KIND_NAMES[body.kind])
    return lines


def respond_edit(
    user_id: str, target_id: str, changes: dict, events: dict[str, Event], now: date
) -> AgentResponse:
    event = events.get(target_id)
    if event is None:
        return AgentResponse(intent="edit", text=NOT_FOUND_TEXT)
    if not service.owns(event, user_id):
        return AgentResponse(intent="edit", text=NOT_OWNER_EDIT)
    update = build_update(changes, event, now)
    if not update:
        return AgentResponse(intent="edit", text=NOTHING_TEXT)
    try:
        body = EventUpdate(**update)
        after = service.resolve_when(event, body, body.model_fields_set)
    except ApiError as e:  # 끝나는 시간이 시작보다 늦지 않은 경우 등
        return AgentResponse(intent="edit", text=e.message)
    lines = _diff(event, body, after)
    if not lines:
        return AgentResponse(intent="edit", text=NOTHING_TEXT)
    card = Card(type="edit_confirm", data={"event": reader.brief(event), "changes": lines})
    return AgentResponse(
        intent="edit",
        text="이렇게 바꿀까요?",
        cards=[card],
        pending_action=PendingAction(type="edit", event_id=event.id, changes=update),
    )


def respond_delete(user_id: str, target_id: str, events: dict[str, Event]) -> AgentResponse:
    event = events.get(target_id)
    if event is None:
        return AgentResponse(intent="delete", text=NOT_FOUND_TEXT)
    if not service.owns(event, user_id):
        return AgentResponse(intent="delete", text=NOT_OWNER_DELETE)
    card = Card(type="delete_confirm", data={"event": reader.brief(event)})
    return AgentResponse(
        intent="delete",
        text=f"'{event.title}' 일정을 지울까요?",
        cards=[card],
        pending_action=PendingAction(type="delete", event_id=event.id),
    )


def confirm_edit(db: Session, user_id: str, group_id: str, action: PendingAction) -> AgentResponse:
    """확인 카드의 [바꾸기]. 앱이 돌려준 값을 믿지 않고 일정·소유자·값을 다시 검증한다(service.update)."""
    if not action.event_id:
        raise bad_request("invalid_action", "처리할 수 없는 요청이에요")
    update = {k: v for k, v in action.changes.items() if k in UPDATE_KEYS}
    try:
        body = EventUpdate(**update)
    except (ValidationError, TypeError) as e:
        raise bad_request("invalid_action", "바꿀 값이 올바르지 않아요") from e
    updated = service.update(db, group_id, user_id, action.event_id, body)
    card = Card(type="event_list", data={"events": [reader.brief(updated)]})
    return AgentResponse(intent="edit", text="바꿨어요.", cards=[card])


def confirm_delete(
    db: Session, user_id: str, group_id: str, action: PendingAction
) -> AgentResponse:
    """확인 카드의 [삭제]. 일정과 소유자를 다시 확인하고 내 줄만 지운다(service.remove)."""
    if not action.event_id:
        raise bad_request("invalid_action", "처리할 수 없는 요청이에요")
    service.remove(db, group_id, user_id, action.event_id)
    return AgentResponse(intent="delete", text="지웠어요.")
