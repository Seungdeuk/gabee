"""에이전트 부탁(함께하기). 모델이 고른 의도와 값을 코드가 검증해 확인 카드로 보여 주고, 사용자가 확인하면 처음부터 다시 검증해서
실행한다(`together.create`·`together.change_recipients`·`together.cancel`).

- 보내기·받는 사람 바꾸기·취소는 상대에게 영향이 가므로 항상 확인 카드를 거친다(요구사항 schedule-agent.md). 확인 전에는 DB 를 바꾸지 않는다.
  상세·현황 질의는 바로 답한다. 부탁 메모는 채팅에서 쓰지 않고 앱 상세 화면에서 사용자가 직접 바꾼다(`PUT /schedule/requests/{id}/memo`).
- 부탁한 사람만 바꾸고 취소한다. 받는 사람이 하면 거부한다. 부탁 내용(제목·날짜 등)은 못 바꾼다 — 취소하고 다시 보낸다.
- 모델에게 보여 주는 [부탁 목록]은 그 사람이 볼 수 있는 만큼만이다(`together.list_mine`): 받는 사람에게는 내 줄과 수락한 사람만 내려와서
  누가 또 받았는지 알려 줄 수 없다. 보낸 사람에게는 어렵겠어요로 답한 사람도 '대기'로 보여 준다(어렵다는 답은 알리지 않는 규칙).
- 서버는 되묻는 동안 아무것도 저장하지 않는다. 보내기 초안은 응답의 `draft`(mode=request)에 실어 보내고 다음 요청에 돌려받는다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from datetime import time as dtime
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy.orm import Session

# ai_assistant 기능 폴더의 mask_text: 목록의 제목(여러 줄, 복원할 일 없음)에서 개인정보를 가린다(chat.py 와 같다).
from app.features.ai_assistant.ingest.masking import mask_text
from app.features.schedule import together
from app.features.schedule.schemas import RequestCreate, RequestRecipients
from app.shared.errors import bad_request

from . import choice as choice_mod
from . import members as members_mod
from . import reader, register
from .members import Member
from .prompts import WEEKDAYS
from .schemas import AgentResponse, Card, Choice, Draft, PendingAction

LIST_LIMIT = 40  # LLM 에 보내는 부탁 수 상한(넘으면 지금과 가까운 순)
PAST_DAYS = 30  # 지난 부탁은 이 기간까지만 보낸다
CARD_LIMIT = 5  # 질의 답에 붙는 카드의 부탁 수 상한
ACTIONS = ("create", "edit", "cancel", "query")

NOT_FOUND_TEXT = "어떤 부탁인지 찾지 못했어요. 부탁 이름이나 날짜를 함께 알려 주세요"
NOT_SENDER_EDIT = "내가 보낸 부탁의 받는 사람만 바꿀 수 있어요"
NOT_SENDER_CANCEL = "내가 보낸 부탁만 취소할 수 있어요"
CONTENT_FIXED_TEXT = "부탁의 제목·날짜·시간·장소는 바꿀 수 없어요. 바꾸려면 부탁을 취소하고 다시 보내 주세요(메모는 바꿀 수 있어요)"
MEMO_SAME_TEXT = "부탁의 메모가 이미 그렇게 되어 있어요"
WHO_HOW_TEXT = "받는 사람을 어떻게 바꿀지 알려 주세요. 모두 빼려면 부탁을 취소해 주세요"
NOTHING_TEXT = "받는 사람이 이미 그렇게 되어 있어요"
NOT_UNDERSTOOD_TEXT = "부탁을 보낼지, 바꿀지, 취소할지, 현황을 볼지 알려 주세요"
NONE_FOUND_TEXT = "해당하는 부탁을 찾지 못했어요"
GIVE_UP_TEXT = (
    "여러 번 여쭤봐도 정보가 부족해서 부탁을 보내지 못했어요. 같이 화면에서 직접 보내 주세요"
)

_STATUS_TEXT = {
    "accepted": "수락",
    "waiting": "대기",
    "declined": "대기",
}  # 어렵다는 답은 보낸 사람에게 알리지 않는다


@dataclass
class RequestView:
    """호출한 사람이 볼 수 있는 부탁들. rows 는 id → `together.list_mine` 의 항목, lines 는 LLM 에 보내는 목록 줄."""

    rows: dict[str, dict] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)


def _when_text(row: dict) -> str:
    day = row["start_date"]
    start, end = row["start_time"], row["end_time"]
    clock = (
        f"{start:%H:%M}~{end:%H:%M}"
        if start and end
        else f"{start:%H:%M}"
        if start
        else "시간 미정"
    )
    return f"{day:%Y-%m-%d}({WEEKDAYS[day.weekday()]}) {clock}"


def _short_when(day: date, start, end) -> str:
    """안내 문장에 쓰는 짧은 날짜·시간(예: 11/12(목) 10:00~11:00, 시간이 없으면 날짜만)."""
    clock = f" {start:%H:%M}~{end:%H:%M}" if start and end else f" {start:%H:%M}" if start else ""
    return f"{day.month}/{day.day}({WEEKDAYS[day.weekday()]}){clock}"


def _row_when(row: dict) -> str:
    return _short_when(row["start_date"], row["start_time"], row["end_time"])


def _line(row: dict, me: str, detail: bool = True) -> str:
    head = f"{row['id']} | {_when_text(row)} | {mask_text(row['title'])}"
    if not detail:  # 가족방: 답이 방에 저장되므로 받는 분·수락 현황은 모델에게도 주지 않는다(id 는 부탁을 고르는 데 필요하다)
        return f"{head} | {'내가 보냄' if row['from_id'] == me else '받음'}"
    recipients = row["recipients"]
    if row["from_id"] == me:
        who = ",".join(f"{r['user_id']}={_STATUS_TEXT[r['status']]}" for r in recipients)
        return f"{head} | 내가 보냄 | 받는분:{who}"
    mine = next((r["status"] for r in recipients if r["user_id"] == me), "waiting")
    answer = {"accepted": "수락", "declined": "어려움"}.get(mine, "대기")
    others = ",".join(
        r["user_id"] for r in recipients if r["status"] == "accepted" and r["user_id"] != me
    )
    return f"{head} | 받음 | 보낸이:{row['from_id']} | 내답:{answer} | 수락:{others or '-'}"


def load(
    db: Session,
    group_id: str,
    user_id: str,
    today: date,
    detail: bool = True,
    room_member_ids: set[str] | None = None,
) -> RequestView:
    """내가 보냈거나 받은 부탁 중 취소되지 않았고 너무 오래되지 않은 것. 지금과 가까운 순으로 상한까지, 날짜순으로 돌려준다.

    `room_member_ids` 를 주면(가족방) 방 구성원 모두가 원래 볼 수 있는 부탁만 남긴다(`together.visible_to_all`). 빠진 부탁은 id·날짜·제목·관계
    어느 것도 모델·카드·답에 가지 않는다(이 목록이 허용 id 의 유일한 출처다). 개인 채팅(None)은 그대로 내 부탁 전체다."""
    oldest = today - timedelta(days=PAST_DAYS)
    allowed = (
        together.visible_to_all(db, group_id, user_id, room_member_ids)
        if room_member_ids is not None
        else None
    )
    rows = [
        r
        for r in together.list_mine(db, group_id, user_id)
        if not r["canceled"]
        and r["start_date"] >= oldest
        and (allowed is None or r["id"] in allowed)
    ]
    rows = sorted(rows, key=lambda r: abs((r["start_date"] - today).days))[:LIST_LIMIT]
    rows.sort(
        key=lambda r: (r["start_date"], r["start_time"] is None, r["start_time"] or 0, r["id"])
    )
    return RequestView(
        rows={r["id"]: r for r in rows}, lines=[_line(r, user_id, detail) for r in rows]
    )


def clean_fields(raw, member_ids: set[str], request_ids: set[str]) -> dict:
    """모델이 돌려준 request 객체를 검증한다. 형식이 틀린 값은 빈 값으로 두고, 목록에 없는 부탁 id 는 버린다."""
    if not isinstance(raw, dict):
        raw = {}
    action = raw.get("action")
    ids = raw.get("request_ids")
    seen: list[str] = []
    for value in ids if isinstance(ids, list) else []:
        if isinstance(value, str) and value in request_ids and value not in seen:
            seen.append(value)
    target = raw.get("target_id")
    return {
        "action": action if action in ACTIONS else "",
        "target_id": target if isinstance(target, str) and target in request_ids else "",
        "request_ids": seen[:CARD_LIMIT],
        "title": register._text(raw.get("title"), register.TITLE_MAX),
        "date": register._text(raw.get("date"), 10),
        "start_time": register._text(raw.get("start_time"), 5),
        "end_time": register._text(raw.get("end_time"), 5),
        "place": register._text(raw.get("place"), register.PLACE_MAX),
        "memo": register._text(raw.get("memo"), register.MEMO_MAX),
        "to_ids": register._ids(raw.get("to_ids"), member_ids),
        "date_ambiguous": raw.get("date_ambiguous") is True,
        "member_ambiguous": raw.get("member_ambiguous") is True,
    }


def _names(ids: list[str], labels: dict[str, str]) -> str:
    return ", ".join(labels[i] for i in ids if i in labels) or "없음"


def _brief(row: dict, me: str, labels: dict[str, str]) -> dict:
    """채팅 카드에 싣는 부탁 요약. 보낸 사람에게는 받는 사람 전원(어렵다는 답은 대기로), 받는 사람에게는 보낸이와 수락한 사람만."""
    sent = row["from_id"] == me
    start, end = row["start_time"], row["end_time"]
    out = {
        "id": row["id"],
        "role": "sent" if sent else "received",
        "title": row["title"],
        "date": f"{row['start_date']:%Y-%m-%d}",
        "time": f"{start:%H:%M}" if start else "",
        "end_time": f"{end:%H:%M}" if end else "",
        "place": row["place"],
        "memo": row["memo"],
    }
    recipients = row["recipients"]
    if sent:
        out["recipients"] = [
            {"name": labels.get(r["user_id"], ""), "status": _STATUS_TEXT[r["status"]]}
            for r in recipients
        ]
    else:
        out["from"] = labels.get(row["from_id"], "")
        out["accepted"] = [
            labels.get(r["user_id"], "")
            for r in recipients
            if r["status"] == "accepted" and r["user_id"] != me
        ]
    return out


def respond(
    db: Session,
    user_id: str,
    group_id: str,
    request_draft: Draft | None,
    fields: dict,
    reply: str,
    members: list[Member],
    view: RequestView,
    today: date | None = None,
    text: str = "",
) -> AgentResponse:
    action = fields["action"]
    labels = {m.id: m.label for m in members}
    if action == "create":
        return _create(db, group_id, request_draft, fields, reply, user_id, members, labels, text)
    if action == "edit":
        return _edit(db, group_id, user_id, fields, view, members, labels, today, text)
    if action == "cancel":
        return _cancel(user_id, fields, view, labels, today, text)
    if action == "query":
        return _query(user_id, fields, reply, view, labels)
    return AgentResponse(intent="request", text=reply or NOT_UNDERSTOOD_TEXT)


def _question(draft: Draft, ambiguous: bool, reply: str) -> str:
    if ambiguous:
        return reply or register.AMBIGUOUS_TEXT
    missing = [
        label
        for label, empty in (
            ("무엇을", not draft.title),
            ("언제", not draft.date),
            ("누구에게", not draft.share_ids),
        )
        if empty
    ]
    return f"부탁을 보내려면 {', '.join(missing)} 알려 주세요"


def _create(
    db: Session,
    group_id: str,
    request_draft: Draft | None,
    fields: dict,
    reply: str,
    user_id: str,
    members: list[Member],
    labels: dict[str, str],
    text: str = "",
) -> AgentResponse:
    member_ids = {m.id for m in members}
    base = request_draft if request_draft is not None and request_draft.mode == "request" else None
    if fields["title"] and fields["date"]:
        base = None  # 제목과 날짜를 모두 말한 문장은 새 요청이다: 옛 초안의 값이 섞이지 않게 한다
    merged = register.merge(base, {**fields, "share_ids": fields["to_ids"], "kind": 0})
    draft = register.normalize(merged, member_ids, user_id, register.today())
    draft = draft.model_copy(update={"mode": "request", "kind": 0, "asks": merged.asks})
    ambiguous = fields["date_ambiguous"]
    if ambiguous:
        draft = draft.model_copy(update={"date": ""})
    who_unclear = fields[
        "member_ambiguous"
    ]  # 같은 호칭의 가족이 여럿이면 누구인지 먼저 되묻는다(정책 #33)
    if who_unclear or not (draft.title and draft.date and draft.share_ids):
        if draft.asks >= register.MAX_ASKS:
            return AgentResponse(intent="request", text=GIVE_UP_TEXT)
        asked = draft.model_copy(update={"asks": draft.asks + 1})
        text = (
            members_mod.ask_text(members, text, user_id, reply or register.MEMBER_UNCLEAR_TEXT)
            if who_unclear and not ambiguous
            else _question(draft, ambiguous, reply)
        )
        return AgentResponse(intent="request", text=text, draft=asked)
    # 제목·날짜·받는 사람이 모두 정해졌으면 확인 카드 없이 바로 보낸다(정책 #40)
    return confirm(
        db, user_id, group_id, PendingAction(type="request_register", draft=draft), members
    )


def _edit(
    db: Session,
    group_id: str,
    user_id: str,
    fields: dict,
    view: RequestView,
    members: list[Member],
    labels: dict[str, str],
    today: date | None = None,
    text: str = "",
) -> AgentResponse:
    row = view.rows.get(fields["target_id"])
    if row is None:
        return AgentResponse(intent="request", text=NOT_FOUND_TEXT)
    if row["from_id"] != user_id:
        return AgentResponse(intent="request", text=NOT_SENDER_EDIT)
    if any(fields[k] for k in ("title", "date", "start_time", "end_time", "place")):
        return AgentResponse(intent="request", text=CONTENT_FIXED_TEXT)
    if today is not None:
        decision, found = _narrow(row, view, user_id, today, text)
        if decision == "ask":
            return _ask_which("request_edit", found, user_id, labels, fields)
        row = found
    return _edit_row(db, group_id, user_id, fields, row, members, labels)


def _edit_row(
    db: Session,
    group_id: str,
    user_id: str,
    fields: dict,
    row: dict,
    members: list[Member],
    labels: dict[str, str],
) -> AgentResponse:
    wanted = [i for i in fields["to_ids"] if i != user_id]
    memo = fields["memo"]
    # 메모는 수락 여부와 상관없이 보낸 사람이 바꿀 수 있다(정책 #25). 이미 수락한 사람의 일정은 독립이라 바뀌지 않는다
    memo_done = None
    if memo and memo != row["memo"]:
        updated = together.change_memo(db, group_id, user_id, row["id"], memo)
        memo_done = AgentResponse(
            intent="request",
            text=f"{_row_when(row)} '{row['title']}' 부탁의 메모를 바꿨어요.",
            cards=[
                Card(type="request_list", data={"requests": [_brief(updated, user_id, labels)]})
            ],
        )
    if memo and not wanted:
        return memo_done or AgentResponse(intent="request", text=MEMO_SAME_TEXT)
    if not wanted:
        return AgentResponse(intent="request", text=WHO_HOW_TEXT)
    current = [r["user_id"] for r in row["recipients"]]
    if set(wanted) == set(current):
        return memo_done or AgentResponse(intent="request", text=NOTHING_TEXT)
    dropped_accepted = [
        r["user_id"]
        for r in row["recipients"]
        if r["status"] == "accepted" and r["user_id"] not in wanted
    ]
    # 받는 사람 변경은 확인 카드 없이 바로 처리한다(정책 #10). 수락한 분을 빼면 그분의 일정이 사라지는 것도 알린다
    done = confirm(
        db,
        user_id,
        group_id,
        PendingAction(type="request_edit", request_id=row["id"], to_ids=wanted),
        members,
    )
    if dropped_accepted:
        done.text += " 수락한 분을 제외해서 그 일정도 같이 사라졌어요."
    if memo_done:
        done.text = memo_done.text + " " + done.text
    return done


def _cancel(
    user_id: str,
    fields: dict,
    view: RequestView,
    labels: dict[str, str],
    today: date | None = None,
    text: str = "",
) -> AgentResponse:
    row = view.rows.get(fields["target_id"])
    if row is None:
        return AgentResponse(intent="request", text=NOT_FOUND_TEXT)
    if row["from_id"] != user_id:
        return AgentResponse(intent="request", text=NOT_SENDER_CANCEL)
    if today is not None:
        decision, found = _narrow(row, view, user_id, today, text)
        if decision == "ask":
            return _ask_which("request_cancel", found, user_id, labels, fields)
        row = found
    return _cancel_row(user_id, row, labels)


def _cancel_row(user_id: str, row: dict, labels: dict[str, str]) -> AgentResponse:
    accepted = [r["user_id"] for r in row["recipients"] if r["status"] == "accepted"]
    # 취소는 상대에게 영향이 가므로 수락한 사람이 없어도 항상 확인 카드를 거친다
    text = f"'{row['title']}' 부탁을 취소할까요?"
    if accepted:
        text = (
            f"{_row_when(row)} '{row['title']}' 부탁은 {_names(accepted, labels)}이(가) 수락했어요. "
            "취소하면 수락하신 분이 만든 일정도 같이 사라져요. 취소할까요?"
        )
    card = Card(
        type="request_confirm",
        data={"action": "cancel", "request": _brief(row, user_id, labels)},
    )
    return AgentResponse(
        intent="request",
        text=text,
        cards=[card],
        pending_action=PendingAction(type="request_cancel", request_id=row["id"]),
    )


def _narrow(row: dict, view: RequestView, user_id: str, today: date, text: str):
    """같은 제목의 내가 보낸 부탁이 여럿이면 시점 규칙으로 좁힌다(일정과 같은 규칙, 정책 #33)."""
    same = sorted(
        (
            r
            for r in view.rows.values()
            if r["from_id"] == user_id and r["title"].strip() == row["title"].strip()
        ),
        key=lambda r: (r["start_date"], r["start_time"] is None, r["start_time"] or 0),
    )
    if len(same) <= 1 or choice_mod.mentions_day(text, row["start_date"]):
        return "one", row
    future = [r for r in same if r["start_date"] >= today]
    if len(future) == 1:
        return "one", future[0]
    if len(future) > 1:
        return "ask", future
    return "one", row


def _ask_which(
    kind: str, found: list, user_id: str, labels: dict[str, str], fields: dict
) -> AgentResponse:
    more = max(len(found) - choice_mod.OPTION_LIMIT, 0)
    found = found[: choice_mod.OPTION_LIMIT]
    title = found[0]["title"]
    return AgentResponse(
        intent="request",
        text=f"'{title}' 부탁이 {len(found) + more}개 있어요. 어느 쪽인가요? 모두인가요?{choice_mod.more_text(more)}",
        cards=[
            Card(
                type="request_list", data={"requests": [_brief(r, user_id, labels) for r in found]}
            )
        ],
        choice=Choice(
            kind=kind,
            event_ids=[r["id"] for r in found],
            changes=fields,
            options=[{"id": r["id"], "line": f"{_row_when(r)} '{r['title']}'"} for r in found],
            more=more,
        ),
    )


def resolve_choice(
    db: Session,
    user_id: str,
    group_id: str,
    chosen: Choice,
    text: str,
    today: date,
    members: list[Member],
):
    """부탁 되묻기에 대한 답을 처리한다. 답으로 읽을 수 없으면 None(새 요청으로 본다)."""
    view = load(db, group_id, user_id, today, detail=True)
    labels = {m.id: m.label for m in members}
    rows = [
        view.rows[i]
        for i in chosen.event_ids
        if i in view.rows and view.rows[i]["from_id"] == user_id
    ]
    if not rows:
        return AgentResponse(intent="request", text=NOT_FOUND_TEXT)
    stand_ins = [
        SimpleNamespace(
            id=r["id"],
            title=r["title"],
            starts_at=datetime.combine(r["start_date"], dtime(), tzinfo=reader.local_tz()),
        )
        for r in rows
    ]
    ids = choice_mod.pick(text, chosen, stand_ins)
    if ids is None:
        return None
    if not ids:
        return AgentResponse(intent="request", text="알겠어요. 그대로 두었어요.")
    picked = [r for r in rows if r["id"] in ids]
    if chosen.kind == "request_cancel":
        if len(picked) > 1:  # 글로 답한 취소는 확인 카드 한 장에 한 건씩이라 하나를 고르게 한다
            one = _ask_which(chosen.kind, picked, user_id, labels, chosen.changes)
            one.text = "부탁 취소는 한 번에 한 건씩 확인해야 해요. 어느 쪽부터 취소할까요?"
            return one
        return _cancel_row(user_id, picked[0], labels)
    texts = [
        _edit_row(db, group_id, user_id, chosen.changes, r, members, labels).text for r in picked
    ]
    return AgentResponse(intent="request", text=" ".join(texts))


def apply_choice(
    db: Session,
    user_id: str,
    group_id: str,
    action: PendingAction,
    today: date,
    members: list[Member],
) -> AgentResponse:
    """선택 카드에서 체크한 부탁을 확인 카드 없이 바로 취소(또는 받는 사람 바꾸기)한다(정책 #39). 부탁은 다시 찾고 보낸 사람인지 확인한다."""
    ids = list(dict.fromkeys(action.event_ids))
    if not ids:
        raise bad_request("invalid_action", "고른 항목이 없어요")
    choice_mod.take(group_id, user_id)
    view = load(db, group_id, user_id, today, detail=True)
    labels = {m.id: m.label for m in members}
    texts: list[str] = []
    for request_id in ids:
        row = view.rows.get(request_id)
        if row is None or row["from_id"] != user_id:
            texts.append(NOT_FOUND_TEXT)
            continue
        if action.choice_kind == "request_cancel":
            one = _cancel_row(user_id, row, labels)
            if (
                one.pending_action is not None
            ):  # 선택 카드에서 골랐으니 확인 카드 없이 바로 취소한다
                texts.append(confirm(db, user_id, group_id, one.pending_action, members).text)
                continue
        else:
            one = _edit_row(db, group_id, user_id, action.changes, row, members, labels)
        texts.append(one.text)
    return AgentResponse(intent="request", text=" ".join(texts))


def _query(
    user_id: str, fields: dict, reply: str, view: RequestView, labels: dict[str, str]
) -> AgentResponse:
    picked = [view.rows[i] for i in fields["request_ids"] if i in view.rows]
    cards = (
        [Card(type="request_list", data={"requests": [_brief(r, user_id, labels) for r in picked]})]
        if picked
        else []
    )
    # 모델이 reply 를 비워도(작은 모델에서 잦다) 카드로 찾은 부탁을 보여 주고 한 줄로 알려 준다
    text = reply or (_found_text(picked, user_id) if picked else NONE_FOUND_TEXT)
    return AgentResponse(intent="request", text=text, cards=cards)


def list_card(rows: list[dict], user_id: str, members: list[Member]) -> Card:
    """부탁 몇 개를 보여 주는 카드(일정 질의에 부탁을 함께 붙일 때도 쓴다)."""
    labels = {m.id: m.label for m in members}
    return Card(type="request_list", data={"requests": [_brief(r, user_id, labels) for r in rows]})


def _found_text(picked: list[dict], user_id: str) -> str:
    """모델 답이 없을 때 쓰는 기본 문장: 부탁 하나면 제목과 수락 현황, 여럿이면 개수."""
    if len(picked) > 1:
        return f"부탁 {len(picked)}개를 찾았어요"
    row = picked[0]
    if row["from_id"] != user_id:
        return f"'{row['title']}' 부탁이에요"
    total = len(row["recipients"])
    accepted = sum(r["status"] == "accepted" for r in row["recipients"])
    status = f"{accepted}/{total}명이 수락했어요" if accepted else "아직 수락한 분이 없어요"
    return f"'{row['title']}' 부탁은 {status}"


def confirm(
    db: Session,
    user_id: str,
    group_id: str,
    action: PendingAction,
    members: list[Member],
) -> AgentResponse:
    """확인 카드의 버튼. AI 를 부르지 않고, 앱이 돌려준 내용은 믿지 않고 처음부터 다시 검증해서 실행한다
    (권한·구성원·값은 `together` 가 다시 확인한다)."""
    labels = {m.id: m.label for m in members}
    member_ids = set(labels)
    try:
        if action.type == "request_register":
            row = _send(db, user_id, group_id, action, member_ids)
            text = (
                f"{_row_when(row)} '{row['title']}' 부탁을 "
                f"{_names([r['user_id'] for r in row['recipients']], labels)}에게 보냈어요."
            )
        elif action.type == "request_edit":
            if not action.request_id or not action.to_ids:
                raise bad_request("invalid_action", "처리할 수 없는 요청이에요")
            row = together.change_recipients(
                db, group_id, user_id, action.request_id, RequestRecipients(to_ids=action.to_ids)
            )
            text = (
                f"{_row_when(row)} '{row['title']}' 부탁의 받는 사람을 "
                f"{_names([r['user_id'] for r in row['recipients']], labels)}(으)로 바꿨어요."
            )
        else:
            if not action.request_id:
                raise bad_request("invalid_action", "처리할 수 없는 요청이에요")
            row = together.cancel(db, group_id, user_id, action.request_id)
            text = f"{_row_when(row)} '{row['title']}' 부탁을 취소했어요."
    except ValidationError as e:
        raise bad_request("invalid_action", "처리할 수 없는 요청이에요") from e
    card = Card(type="request_list", data={"requests": [_brief(row, user_id, labels)]})
    return AgentResponse(intent="request", text=text, cards=[card])


def _send(db: Session, user_id: str, group_id: str, action: PendingAction, member_ids: set[str]):
    if action.draft is None:
        raise bad_request("invalid_action", "처리할 수 없는 요청이에요")
    draft = register.normalize(action.draft, member_ids, user_id, register.today())
    if not (draft.title and draft.date and draft.share_ids):
        raise bad_request("draft_incomplete", "부탁에 필요한 제목, 날짜, 받는 사람이 없어요")
    return together.create(
        db,
        group_id,
        user_id,
        RequestCreate(
            title=draft.title,
            start_date=date.fromisoformat(draft.date),
            start_time=register._to_time(draft.start_time),
            end_time=register._to_time(draft.end_time),
            place=draft.place,
            memo=draft.memo,
            to_ids=draft.share_ids,
        ),
    )
