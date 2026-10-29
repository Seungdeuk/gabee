"""에이전트 등록. 모델이 돌려준 register 값을 검증해 초안과 합치고, 필수(제목·날짜)가 빠졌으면 되묻고,
공유 대상이 있으면 확인 카드를 보내고, 아니면 바로 등록한다.

모델 출력도 앱이 돌려준 초안도 믿지 않는다: 날짜·시간 형식, 길이, 구성원 id 를 코드가 다시 확인한다.
등록은 내 일정만 만든다. 공유는 사용자가 요청했을 때만 대상에 넣고 확인 카드를 거친다(`confirm`).
서버는 되묻는 동안 아무것도 저장하지 않는다 — 초안은 응답에 실어 보내고 다음 요청에 돌려받는다.
"""

import re
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.schedule import service
from app.features.schedule.models import Event
from app.features.schedule.schemas import EventCreate
from app.features.schedule.timeutil import local_tz
from app.shared.errors import bad_request

from .members import Member
from .schemas import AgentResponse, Card, Draft, PendingAction

MAX_ASKS = 2  # 같은 등록에서 되묻는 최대 횟수
DATE_SPAN_DAYS = 730  # 오늘 앞뒤로 받을 수 있는 날짜 범위
TITLE_MAX = 120
PLACE_MAX = 200
MEMO_MAX = 1000
MAX_IDS = 20
DEFAULT_MINUTES = 60  # 시작만 말했을 때 끝 시간 = 시작 + 1시간
DEFAULT_KIND = 2  # 모델이 형태를 못 정하면 할 일(체크하면 되는 쪽이 안전하다)

GIVE_UP_TEXT = (
    "여러 번 여쭤봐도 정보가 부족해서 등록하지 못했어요. 일정 등록 화면에서 직접 입력해 주세요"
)
AMBIGUOUS_TEXT = "날짜를 정확히 알려 주세요. 예: 10월 30일"

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _text(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _ids(value, allowed: set[str]) -> list[str]:
    """모델·앱이 준 id 중 이 가족 구성원인 것만, 중복 없이."""
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for item in value:
        if isinstance(item, str) and item in allowed and item not in seen:
            seen.append(item)
    return seen[:MAX_IDS]


def clean_fields(raw, member_ids: set[str]) -> dict:
    """모델이 돌려준 register 객체를 검증한다. 형식이 틀린 값은 빈 값으로 둔다(날짜 범위는 `normalize` 에서)."""
    if not isinstance(raw, dict):
        raw = {}
    kind = raw.get("kind")
    return {
        "title": _text(raw.get("title"), TITLE_MAX),
        "date": _text(raw.get("date"), 10),
        "start_time": _text(raw.get("start_time"), 5),
        "end_time": _text(raw.get("end_time"), 5),
        "kind": kind if kind in (1, 2) and not isinstance(kind, bool) else 0,
        "place": _text(raw.get("place"), PLACE_MAX),
        "memo": _text(raw.get("memo"), MEMO_MAX),
        "share_ids": _ids(raw.get("share_ids"), member_ids),
        "date_ambiguous": raw.get("date_ambiguous") is True,
    }


def merge(draft: Draft | None, fields: dict) -> Draft:
    """새로 읽은 값이 있으면 그것을, 비었으면 초안의 값을 쓴다."""
    base = draft or Draft()

    def pick(key: str):
        return fields.get(key) or getattr(base, key)

    return Draft(
        title=pick("title"),
        date=pick("date"),
        start_time=pick("start_time"),
        end_time=pick("end_time"),
        kind=pick("kind"),
        place=pick("place"),
        memo=pick("memo"),
        share_ids=pick("share_ids"),
        asks=base.asks,
    )


def today() -> date:
    return datetime.now(UTC).astimezone(local_tz()).date()


def valid_date(value: str, now: date) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return ""
    return value if abs((parsed - now).days) <= DATE_SPAN_DAYS else ""


def valid_time(value: str) -> str:
    return value if _TIME.match(value) else ""


def plus_hour(value: str) -> str:
    start = datetime.strptime(value, "%H:%M")
    end = start + timedelta(minutes=DEFAULT_MINUTES)
    return "23:59" if end.day != start.day else end.strftime("%H:%M")


def normalize(draft: Draft, member_ids: set[str], me: str, now: date) -> Draft:
    """초안을 등록 가능한 모양으로 다듬는다: 시간은 둘 다 있거나 둘 다 없게, 공유 대상에서 나는 뺀다."""
    start = valid_time(draft.start_time)
    end = valid_time(draft.end_time) if start else ""
    if start and (not end or end <= start):
        end = plus_hour(start)
    return draft.model_copy(
        update={
            "title": draft.title.strip(),
            "date": valid_date(draft.date, now),
            "start_time": start,
            "end_time": end,
            "place": draft.place.strip(),
            "memo": draft.memo.strip(),
            "share_ids": [i for i in _ids(draft.share_ids, member_ids) if i != me],
        }
    )


def _question(need_title: bool, need_date: bool, ambiguous: bool, reply: str) -> str:
    if ambiguous:
        return reply or AMBIGUOUS_TEXT
    if need_title and need_date:
        return "제목과 날짜가 빠졌어요. 무엇을 언제로 등록할까요?"
    if need_date:
        return "날짜가 빠졌어요. 언제로 등록할까요?"
    return "제목이 빠졌어요. 무엇을 등록할까요?"


def _hm(value: time | None) -> str:
    return f"{value:%H:%M}" if value else ""


def _to_time(value: str) -> time | None:
    return datetime.strptime(value, "%H:%M").time() if value else None


def _existing(db: Session, user_id: str, group_id: str, draft: Draft) -> Event | None:
    """같은 사람이 같은 제목·날짜·시작 시각으로 이미 등록한 일정(지운 것 제외)."""
    start = _to_time(draft.start_time)
    query = select(Event).where(
        Event.group_id == group_id,
        Event.user_id == user_id,
        Event.deleted_at.is_(None),
        Event.title == draft.title,
        Event.start_date == date.fromisoformat(draft.date),
        Event.start_time.is_(None) if start is None else Event.start_time == start,
    )
    return db.scalars(query).first()


def _created(db: Session, user_id: str, group_id: str, draft: Draft, members: list[Member]):
    # 같은 요청을 다시 보내거나 되묻는 답을 합쳐 다시 보내도 같은 일정이 두 번 생기지 않게 한다(공유 등록은 받는 사람 복사본이 있어 제외)
    already = None if draft.share_ids else _existing(db, user_id, group_id, draft)
    event: Event = already or service.create(
        db,
        group_id,
        user_id,
        EventCreate(
            title=draft.title,
            start_date=date.fromisoformat(draft.date),
            start_time=_to_time(draft.start_time),
            end_time=_to_time(draft.end_time),
            kind=draft.kind or DEFAULT_KIND,
            place=draft.place,
            memo=draft.memo,
            share_with=draft.share_ids,
            source="chat",
        ),
    )
    card = Card(
        type="registered",
        data={
            "event_id": event.id,
            "kind": event.kind,
            "title": event.title,
            "date": event.start_date.isoformat(),
            "start_time": _hm(event.start_time),
            "end_time": _hm(event.end_time),
            "place": event.place,
            "shared": len(draft.share_ids),
            **({"already": True} if already else {}),
        },
    )
    return AgentResponse(
        intent="register", text="이미 있는 일정이에요." if already else "등록했어요.", cards=[card]
    )


def respond(
    db: Session,
    user_id: str,
    group_id: str,
    request_draft: Draft | None,
    fields: dict,
    reply: str,
    members: list[Member],
    share_all: bool = False,
) -> AgentResponse:
    member_ids = {m.id for m in members}
    if share_all:  # 모델이 일부만 고르거나 비워 둬도 가족 전체로 정한다
        fields = {**fields, "share_ids": [m.id for m in members if m.id != user_id]}
    if fields.get("title") and fields.get("date"):
        request_draft = None  # 제목과 날짜를 모두 말한 문장은 새 요청이다: 옛 초안의 시간·장소·공유 대상이 섞이지 않게 한다
    draft = normalize(merge(request_draft, fields), member_ids, user_id, today())
    ambiguous = fields["date_ambiguous"]
    if ambiguous:
        draft = draft.model_copy(update={"date": ""})
    need_title, need_date = not draft.title, not draft.date
    if need_title or need_date:
        if draft.asks >= MAX_ASKS:
            return AgentResponse(intent="register", text=GIVE_UP_TEXT)
        asked = draft.model_copy(update={"asks": draft.asks + 1})
        return AgentResponse(
            intent="register",
            text=_question(need_title, need_date, ambiguous, reply),
            draft=asked,
        )
    if draft.share_ids:
        return _share_confirm(draft, members)
    return _created(db, user_id, group_id, draft, members)


def _share_confirm(draft: Draft, members: list[Member]) -> AgentResponse:
    labels = {m.id: m.label for m in members}
    who = [{"id": i, "name": labels[i]} for i in draft.share_ids if i in labels]
    card = Card(
        type="register_confirm",
        data={
            "title": draft.title,
            "kind": draft.kind or DEFAULT_KIND,
            "date": draft.date,
            "start_time": draft.start_time,
            "end_time": draft.end_time,
            "place": draft.place,
            "share": who,
        },
    )
    names = ", ".join(w["name"] for w in who)
    return AgentResponse(
        intent="register",
        text=f"{names}에게 공유해서 등록할까요?",
        cards=[card],
        pending_action=PendingAction(type="register", draft=draft),
    )


def confirm(
    db: Session,
    user_id: str,
    group_id: str,
    action: PendingAction,
    share: bool,
    members: list[Member],
) -> AgentResponse:
    """확인 카드의 버튼. AI 를 부르지 않고, 앱이 돌려준 초안을 처음부터 다시 검증해서 등록한다."""
    if action.type != "register" or action.draft is None:
        raise bad_request("invalid_action", "처리할 수 없는 요청이에요")
    member_ids = {m.id for m in members}
    draft = normalize(action.draft, member_ids, user_id, today())
    if not share:
        draft = draft.model_copy(update={"share_ids": []})
    if not draft.title or not draft.date:
        raise bad_request("draft_incomplete", "등록에 필요한 제목이나 날짜가 없어요")
    return _created(db, user_id, group_id, draft, members)
