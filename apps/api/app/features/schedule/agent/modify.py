"""에이전트 수정·삭제. 모델이 고른 대상 일정과 바뀔 값을 코드가 검증해 확인 카드로 보여 주고, 사용자가 확인하면
처음부터 다시 검증해서 실행한다(`service.update`·`service.remove`).

- 대상은 모델이 일정 목록의 id 만 고른다. 삭제는 같은 이름이 여럿이면 지금과 가장 가까운 하나를 고르고, 확인 카드에 날짜가
  보이니 틀리면 사용자가 취소한다. 수정은 공유 대상을 바꾸지 않으면 카드 없이 바로 처리하므로, 하나를 가릴 수 없으면
  대상을 비워 되묻는다. 목록에 없는 id 는 버린다.
- 내 줄만 고치고 지운다(`service.owns`). 복사본은 독립이라 원본을 고치거나 지워도 공유받은 사람의 일정은 그대로다.
- 공유 대상은 원본 주인만 바꾼다(가족 구성원만). 공유받은 일정과 부탁을 수락해 생긴 일정은 거부하고, 공유받은 사람에게는
  누구에게 공유됐는지도 알려 주지 않는다(`share_targets_for_prompt`). 사람을 빼면 그 사람의 복사본이 지워진다(`service.update`).
- 확인 요청의 내용은 앱이 돌려준 것이므로 믿지 않는다: 일정을 다시 찾고, 소유자를 다시 확인하고, 값을 다시 검증한다.
"""

from datetime import date, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.features.schedule import repository as schedule_repo
from app.features.schedule import service
from app.features.schedule.models import Event
from app.features.schedule.schemas import EventUpdate
from app.shared.errors import ApiError, bad_request

from . import reader, register
from .members import Member
from .schemas import AgentResponse, Card, PendingAction

TITLE_MAX = 120
PLACE_MAX = 200
MEMO_MAX = 1000
CLEARABLE = ("time", "place", "memo")
# 확인 요청에서 받는 바꿀 값의 이름(EventUpdate 의 필드). 그 밖의 이름은 버린다
UPDATE_KEYS = (
    "title",
    "start_date",
    "start_time",
    "end_time",
    "kind",
    "place",
    "memo",
    "share_with",
)
WEEKDAYS = "월화수목금토일"
KIND_NAMES = {1: "약속", 2: "할 일"}

NOT_FOUND_TEXT = "어떤 일정인지 찾지 못했어요. 일정 이름이나 날짜를 함께 알려 주세요"
NOT_OWNER_EDIT = "내 일정만 고칠 수 있어요"
NOT_OWNER_DELETE = "내 일정만 지울 수 있어요"
NOTHING_TEXT = "바꿀 내용을 찾지 못했어요. 무엇을 어떻게 바꿀지 알려 주세요"
UNDO_HINT = " 되돌리려면 말씀해 주세요."
NOT_SHARE_OWNER = "공유 대상은 일정을 처음 만든 분만 바꿀 수 있어요"
SHARE_PERSONAL_ONLY = "공유 대상은 개인 채팅에서만 바꿀 수 있어요"


def _text(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def clean_changes(raw, member_ids=frozenset()) -> dict:
    """모델이 돌려준 changes 를 검증한다. 형식이 틀린 값은 빈 값(바꾸지 않음)으로 둔다.
    공유 대상은 share_change 가 true 일 때만 읽고, 가족 구성원 id 만 남긴다(빈 목록은 모두 빼 달라는 뜻)."""
    if not isinstance(raw, dict):
        raw = {}
    share_change = raw.get("share_change") is True
    share_ids = raw.get("share_ids")
    share_ids = (
        [i for i in dict.fromkeys(share_ids) if isinstance(i, str) and i in member_ids]
        if share_change and isinstance(share_ids, list)
        else []
    )
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
        "share_change": share_change,
        "share_ids": share_ids,
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


def can_reshare(event: Event) -> bool:
    """공유 대상을 바꿀 수 있는 일정인가: 내가 처음 만든 원본(공유받은 복사본·부탁을 수락해 생긴 일정이 아님)."""
    return event.origin_id is None and event.request_id is None


def share_targets_for_prompt(event: Event, user_id: str) -> list[str] | None:
    """모델에게 알려 줄 공유 대상(구성원 id). 내가 공유한 원본일 때만이고, 공유받은 일정은 누구에게 공유됐는지 숨긴다."""
    if not (service.owns(event, user_id) and can_reshare(event)):
        return None
    return list(getattr(event, "shared_ids", None) or []) or None


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


def _share_line(current: list[str], new: list[str], labels: dict[str, str]) -> dict:
    def text(ids: list[str]) -> str:
        return ", ".join(labels[i] for i in ids if i in labels) or "없음"

    return {"label": "공유", "before": text(current), "after": text(new)}


def respond_edit(
    user_id: str,
    target_id: str,
    changes: dict,
    events: dict[str, Event],
    now: date,
    members: list[Member] | None = None,
    channel: str = "personal",
    db: Session | None = None,
    group_id: str | None = None,
) -> AgentResponse:
    """공유 대상을 바꾸지 않는 수정(제목·날짜·시간·장소·메모)은 카드 없이 바로 처리한다.
    공유 대상 변경은 받은 사람의 일정이 사라질 수 있어 확인 카드를 거친다(#11 은 이 부분이 남아 있다).
    db 를 주지 않으면(순수 계산 호출) 항상 카드만 만든다."""
    event = events.get(target_id)
    if event is None:
        return AgentResponse(intent="edit", text=NOT_FOUND_TEXT)
    if not service.owns(event, user_id):
        return AgentResponse(intent="edit", text=NOT_OWNER_EDIT)
    share_new: list[str] | None = None
    current: list[str] = []
    if changes.get("share_change"):
        if channel != "personal":  # 가족 채팅 화면은 가족이 함께 봐서 누구에게 공유했는지 드러난다
            return AgentResponse(intent="edit", text=SHARE_PERSONAL_ONLY)
        if not can_reshare(event):
            return AgentResponse(intent="edit", text=NOT_SHARE_OWNER)
        current = list(getattr(event, "shared_ids", None) or [])
        wanted = [i for i in changes["share_ids"] if i != user_id]
        if set(wanted) != set(current):
            share_new = wanted
    update = build_update(changes, event, now)
    if share_new is not None:
        update["share_with"] = share_new
    if not update:
        return AgentResponse(intent="edit", text=NOTHING_TEXT)
    try:
        body = EventUpdate(**update)
        after = service.resolve_when(event, body, body.model_fields_set)
    except ApiError as e:  # 끝나는 시간이 시작보다 늦지 않은 경우 등
        return AgentResponse(intent="edit", text=e.message)
    lines = _diff(event, body, after)
    text = f"{reader.event_text(event)} 일정을 이렇게 바꿀까요?"
    if share_new is not None:
        labels = {m.id: m.label for m in members or []}
        lines.append(_share_line(current, share_new, labels))
        removed = [labels[i] for i in current if i not in share_new and i in labels]
        if removed:
            text += f" {', '.join(removed)}님은 공유에서 빠지고, 받은 일정도 같이 사라져요."
    if not lines:
        return AgentResponse(intent="edit", text=NOTHING_TEXT)
    if share_new is None and db is not None and group_id:
        done = confirm_edit(
            db, user_id, group_id, PendingAction(type="edit", event_id=event.id, changes=update)
        )
        done.text += UNDO_HINT
        return done
    card = Card(type="edit_confirm", data={"event": reader.brief(event), "changes": lines})
    return AgentResponse(
        intent="edit",
        text=text,
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
        text=f"{reader.event_text(event)} 일정을 지울까요?",
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
    return AgentResponse(
        intent="edit", text=f"{reader.event_text(updated)} 일정을 바꿨어요.", cards=[card]
    )


def confirm_delete(
    db: Session, user_id: str, group_id: str, action: PendingAction
) -> AgentResponse:
    """확인 카드의 [삭제]. 일정과 소유자를 다시 확인하고 내 줄만 지운다(service.remove)."""
    if not action.event_id:
        raise bad_request("invalid_action", "처리할 수 없는 요청이에요")
    before = schedule_repo.get(db, group_id, action.event_id, user_id)
    named = reader.event_text(before) if before else ""  # 지우기 전에 어떤 일정인지 읽어 둔다
    service.remove(db, group_id, user_id, action.event_id)
    text = f"{named} 일정을 지웠어요." if named else "지웠어요."
    return AgentResponse(intent="delete", text=text)
