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

import re
from datetime import date, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.features.schedule import repository as schedule_repo
from app.features.schedule import service
from app.features.schedule.models import Event
from app.features.schedule.schemas import EventUpdate
from app.shared.errors import ApiError, bad_request

from . import choice as choice_mod
from . import members as members_mod
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

NOT_FOUND_TEXT = "해당하는 일정이 등록되어 있지 않아요. 이름이나 날짜를 다시 알려 주세요"
NOT_OWNER_EDIT = "내 일정만 고칠 수 있어요"
NOT_OWNER_DELETE = "내 일정만 지울 수 있어요"
NOTHING_TEXT = "바꿀 내용을 읽지 못해서 바꾸지 못했어요. 예: 시간을 3시로"

REMOVE_WORDS = re.compile(r"빼|제외|취소|그만|해제")


def _share_nothing(event: Event, text: str) -> str:
    """공유를 바꾸려 했는데 바뀐 게 없을 때: 빼 달라는 말이면 이미 아무도 없다고, 아니면 말한 사람이 가족에 없다고 알린다."""
    named = reader.event_text(event)
    if REMOVE_WORDS.search(text):
        return f"{named} 일정은 이미 공유받는 사람이 없어요."
    return f"{named} 일정을 공유하지 못했어요. 말씀하신 분을 가족에서 찾지 못했어요."
NOT_FOUND_OFFER_TEXT = "해당하는 일정이 등록되어 있지 않아요. 새로 등록하려면 제목과 날짜를 알려 주세요"
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
        "member_ambiguous": raw.get("member_ambiguous") is True,
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


def _nothing_text(event: Event, changes: dict) -> str:
    """바꿀 내용이 정해졌는데 일정이 이미 그렇게 되어 있으면 그렇게 알리고, 바꿀 내용을 말하지 않았을 때만 되묻는다."""
    said = any(
        changes.get(k)
        for k in ("title", "date", "start_time", "end_time", "place", "memo", "clear", "kind")
    )
    if said:
        return f"{reader.event_text(event)} 일정은 이미 그렇게 되어 있어요."
    return NOTHING_TEXT


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
    text: str = "",
    related=(),
    reply: str = "",
    unnamed: bool = False,
) -> AgentResponse:
    """수정(제목·날짜·시간·장소·메모와 원본자의 공유 대상 변경)은 카드 없이 바로 처리한다(정책 #32).
    받은 사람의 일정은 독립이라 원본을 고쳐도 영향이 없고, 삭제만 확인 카드를 거친다.
    같은 제목의 일정이 여럿이면 시점 규칙으로 좁히거나 후보를 보여 주며 되묻는다(`choice.narrow`, 정책 #33).
    db 를 주지 않으면(순수 계산 호출) 카드만 만든다."""
    event = events.get(target_id)
    if event is None:
        wants = any(
            changes.get(k)
            for k in (
                "title",
                "date",
                "start_time",
                "end_time",
                "place",
                "memo",
                "clear",
                "share_change",
            )
        )
        found = choice_mod.which_candidates(events, now) if wants and unnamed else []
        if found:  # 일정을 이름 없이 가리켰으면 후보를 보여 주며 어느 일정인지 되묻는다(정책 #35)
            return choice_mod.ask_which("edit", found, changes)
        # 이름을 말했는데 없으면 찾지 못했다고 안내하고 새 등록을 권한다
        return AgentResponse(intent="edit", text=NOT_FOUND_OFFER_TEXT)
    if not service.owns(event, user_id):
        return AgentResponse(intent="edit", text=NOT_OWNER_EDIT)
    # 모델이 공유 변경으로 표시하지 못해도, 바꿀 다른 내용이 없고 문장에서 같은 호칭의 가족이 여럿 잡히면 코드가 되묻는다
    # (되묻기 답을 처리할 때는 text 가 비어 있다)
    only_who = not any(
        changes.get(k)
        for k in ("title", "date", "start_time", "end_time", "place", "memo", "clear", "share_ids")
    )
    same_call = bool(
        only_who and members and text and members_mod.same_call(members, text, user_id)
    )
    if (changes.get("share_change") and changes.get("member_ambiguous")) or same_call:
        # 같은 호칭의 가족이 여럿이면 누구인지 되묻고, 이름으로 답하면 그 사람을 더해 다시 처리한다(정책 #33)
        changes = {**changes, "share_change": True}
        ask = members_mod.ask_text(
            members or [], text, user_id, reply or register.MEMBER_UNCLEAR_TEXT
        )
        return choice_mod.ask_member(event, changes, ask)
    if not changes.get("share_change"):
        decision, found = choice_mod.narrow(event, events, now, "edit", text, related)
        if decision == "ask" and build_update(changes, event, now):
            return choice_mod.ask_response("edit", found, changes)
        if decision == "one":
            event = found
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
    if not update and changes.get("share_change") and current:
        # 말한 사람이 이미 공유 대상이면 바뀔 것이 없다: "무엇을 바꿀지"가 아니라 이미 공유되어 있다고 알린다
        labels = {m.id: m.label for m in members or []}
        who = ", ".join(labels[i] for i in current if i in labels)
        if who:
            return AgentResponse(
                intent="edit",
                text=f"{reader.event_text(event)} 일정은 이미 {who}님에게 공유되어 있어요.",
            )
    if not update and changes.get("share_change"):
        # 공유받는 사람이 이미 없는 일정에서 공유를 빼 달라는 경우: 이미 그렇게 되어 있다고 알린다
        return AgentResponse(
            intent="edit",
            text=_share_nothing(event, text),
        )
    if not update:  # 읽을 수 있는 값이 하나도 없다
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
        if share_new is not None:  # 공유만 바꾸려 했는데 바뀐 게 없다: 이유를 밝힌다
            return AgentResponse(intent="edit", text=_share_nothing(event, text))
        return AgentResponse(intent="edit", text=_nothing_text(event, changes))
    if db is not None and group_id:
        done = confirm_edit(
            db, user_id, group_id, PendingAction(type="edit", event_id=event.id, changes=update)
        )
        # 카드 없이 바로 바꾸므로 무엇이 어떻게 바뀌었는지 안내에 밝힌다(잘못 읽었으면 사용자가 바로 알아챈다)
        summary = "; ".join(f"{c['label']} {c['before']} → {c['after']}" for c in lines)
        if summary:
            done.text = done.text.replace(" 일정을 바꿨어요.", f" 일정을 바꿨어요 ({summary}).", 1)
        if share_new is not None:
            labels = {m.id: m.label for m in members or []}
            removed = [labels[i] for i in current if i not in share_new and i in labels]
            added = [labels[i] for i in share_new if i not in current and i in labels]
            if set(update) == {
                "share_with"
            }:  # 공유만 바꿨으면 요약 대신 공유한 사실을 직접 알리고 카드는 붙이지 않는다
                named = reader.event_text(event)
                parts = []
                if added:
                    parts.append(f"{named} 일정을 {', '.join(added)}님에게 공유했어요.")
                if removed:
                    parts.append(
                        f"{named} 일정 공유에서 {', '.join(removed)}님을 뺐어요. 받은 일정도 같이 사라졌어요."
                    )
                done.text = " ".join(parts) or done.text
                done.cards = []
                removed = []  # 위 문장에 이미 담았다
            if removed:
                done.text += (
                    f" {', '.join(removed)}님은 공유에서 뺐고, 받은 일정도 같이 사라졌어요."
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


def respond_delete(
    user_id: str,
    target_id: str,
    events: dict[str, Event],
    now: date | None = None,
    text: str = "",
    related=(),
    many=(),
    unnamed: bool = False,
) -> AgentResponse:
    if many:  # 같은 조건의 여러 건(예: 오늘 일정 다 삭제): 한 장의 카드로 묻고 확인하면 건별로 지운다(정책 #28)
        picked = [
            events[i]
            for i in dict.fromkeys(many)
            if i in events and service.owns(events[i], user_id)
        ]
        picked.sort(key=lambda e: reader.to_local(e.starts_at))
        if len(picked) >= 2:
            return _ask_delete_many(picked)
    event = events.get(target_id)
    if event is None:
        found = choice_mod.which_candidates(events, now) if now is not None and unnamed else []
        if found:
            return choice_mod.ask_which("delete", found)
        return AgentResponse(intent="delete", text=NOT_FOUND_OFFER_TEXT)
    if not service.owns(event, user_id):
        return AgentResponse(intent="delete", text=NOT_OWNER_DELETE)
    if now is not None:
        decision, found = choice_mod.narrow(event, events, now, "delete", text, related)
        if decision == "ask":
            return choice_mod.ask_response("delete", found)
        if decision == "past":
            return choice_mod.ask_response("delete", found, past=True)
        event = found
        if not service.owns(event, user_id):
            return AgentResponse(intent="delete", text=NOT_OWNER_DELETE)
    card = Card(type="delete_confirm", data={"event": reader.brief(event)})
    return AgentResponse(
        intent="delete",
        text=f"{reader.event_text(event)} 일정을 지울까요?",
        cards=[card],
        pending_action=PendingAction(type="delete", event_id=event.id),
    )


MANY_LIMIT = 10  # 한 번에 지울 수 있는 일정 수


def _ask_delete_many(picked: list) -> AgentResponse:
    over = len(picked) - MANY_LIMIT
    shown = picked[:MANY_LIMIT]
    lines = ", ".join(reader.event_text(e) for e in shown)
    head = f"{len(shown)}개 일정을 지울까요? {lines}"
    if over > 0:
        head = f"한 번에 {MANY_LIMIT}개까지만 지울 수 있어서 먼저 {len(shown)}개를 지울까요? {lines} 나머지 {over}개는 다시 말씀해 주세요."
    card = Card(
        type="delete_confirm",
        data={"event": reader.brief(shown[0]), "events": [reader.brief(e) for e in shown]},
    )
    return AgentResponse(
        intent="delete",
        text=head,
        cards=[card],
        pending_action=PendingAction(type="delete", event_ids=[e.id for e in shown]),
    )


def delete_many(
    db: Session, user_id: str, group_id: str, ids: list[str]
) -> tuple[list[str], list[str]]:
    """일정마다 하나씩 지운다. 못 지운 것은 한 번 더 시도하고, 지운 일정과 못 지운 일정의 이름을 돌려준다."""
    done: list[str] = []
    failed: list[str] = []
    for event_id in list(dict.fromkeys(ids))[:MANY_LIMIT]:
        before = schedule_repo.get(db, group_id, event_id, user_id)
        if before is None:
            continue
        named = reader.event_text(before)
        for attempt in range(2):
            try:
                service.remove(db, group_id, user_id, event_id)
                done.append(named)
                break
            except ApiError:
                if attempt:
                    failed.append(named)
    return done, failed


def many_text(done: list[str], failed: list[str]) -> str:
    if not done:
        return (
            f"{', '.join(failed) or '일정'}을 지우지 못했어요. 잠시 뒤 다시 말씀해 주세요."
            if failed
            else NOT_FOUND_TEXT
        )
    if failed:
        return f"{', '.join(done)}까지 지웠고 {', '.join(failed)}은 못 지웠어요."
    return (
        f"{len(done)}개 일정을 지웠어요: {', '.join(done)}."
        if len(done) > 1
        else f"{done[0]} 일정을 지웠어요."
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
    if action.event_ids:
        done, failed = delete_many(db, user_id, group_id, action.event_ids)
        return AgentResponse(intent="delete", text=many_text(done, failed))
    if not action.event_id:
        raise bad_request("invalid_action", "처리할 수 없는 요청이에요")
    before = schedule_repo.get(db, group_id, action.event_id, user_id)
    named = reader.event_text(before) if before else ""  # 지우기 전에 어떤 일정인지 읽어 둔다
    service.remove(db, group_id, user_id, action.event_id)
    text = f"{named} 일정을 지웠어요." if named else "지웠어요."
    return AgentResponse(intent="delete", text=text)


def resolve_choice(
    db: Session, user_id: str, group_id: str, chosen, text: str, today: date
) -> AgentResponse | None:
    """되묻기(`choice.ask_response`)에 대한 사용자의 답을 처리한다. 답으로 읽을 수 없으면 None(새 요청으로 본다).
    사용자가 후보 중에서 골랐으므로 삭제도 확인 카드 없이 바로 처리한다(정책 #29). 일정은 다시 찾고 소유자를 확인한다."""
    events = []
    for event_id in chosen.event_ids:
        found = schedule_repo.get(db, group_id, event_id, user_id)
        if found is not None and service.owns(found, user_id):
            events.append(found)
    if not events:
        return AgentResponse(intent=chosen.kind, text=NOT_FOUND_TEXT)
    if chosen.members:  # 공유할 사람을 이름으로 답하면 그 사람을 더해 수정을 마저 처리한다
        family = members_mod.load(db, group_id)
        who = choice_mod.pick_members(text, family, user_id)
        if not who:
            return None
        merged = list(dict.fromkeys([*chosen.changes.get("share_ids", []), *who]))
        changes = {**chosen.changes, "share_ids": merged, "member_ambiguous": False}
        return respond_edit(
            user_id,
            events[0].id,
            changes,
            {events[0].id: events[0]},
            today,
            family,
            "personal",
            db,
            group_id,
        )
    ids = choice_mod.pick(text, chosen, events)
    if ids is None:
        return None
    if chosen.kind == "edit" and chosen.changes.get("share_change") and ids:
        family = members_mod.load(
            db, group_id
        )  # 공유 대상 변경은 한 일정씩 원본자 규칙을 거쳐 처리한다
        one = next(e for e in events if e.id == ids[0])
        return respond_edit(
            user_id, one.id, chosen.changes, {one.id: one}, today, family, "personal", db, group_id
        )
    verb = "바꾸지" if chosen.kind == "edit" else "지우지"
    if not ids:
        return AgentResponse(intent=chosen.kind, text=f"알겠어요. {verb} 않았어요.")
    picked = [e for e in events if e.id in set(ids)]
    try:
        if (
            chosen.kind == "delete"
        ):  # 사용자가 후보 중에서 골랐으므로 카드 없이 바로 지운다(정책 #29)
            done, failed = delete_many(db, user_id, group_id, [e.id for e in picked])
            return AgentResponse(intent="delete", text=many_text(done, failed))
        cards = []
        texts = []
        family = members_mod.load(db, group_id)
        for event in picked:
            one = respond_edit(
                user_id,
                event.id,
                chosen.changes,
                {event.id: event},
                today,
                family,
                "personal",
                db,
                group_id,
            )
            if one.cards:
                cards += one.cards
                texts.append(one.text.removesuffix(UNDO_HINT))
    except ApiError as e:
        return AgentResponse(intent=chosen.kind, text=e.message)
    if not cards:
        return AgentResponse(
            intent="edit", text=_nothing_text(picked[0], chosen.changes) if picked else NOTHING_TEXT
        )
    return AgentResponse(intent="edit", text=f"{' '.join(texts)}{UNDO_HINT}", cards=cards)
