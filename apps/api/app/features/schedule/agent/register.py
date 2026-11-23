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

from . import choice, reader
from . import members as members_mod
from . import period as period_mod
from .members import Member
from .schemas import AgentResponse, Card, Choice, Draft, PendingAction

MAX_ASKS = 2  # 같은 등록에서 되묻는 최대 횟수
DATE_SPAN_DAYS = 730  # 오늘 앞뒤로 받을 수 있는 날짜 범위
TITLE_MAX = 120
PLACE_MAX = 200
MEMO_MAX = 1000
MAX_IDS = 20
DEFAULT_MINUTES = 60  # 시작만 말했을 때 끝 시간 = 시작 + 1시간
MAX_REL_WEEKS = 104  # date_rel.weeks 절대값 상한
NO_REL = {"weeks": 0, "days": 0, "weekday": -1}  # 상대 날짜 표현 없음
DEFAULT_KIND = 2  # 모델이 형태를 못 정하면 할 일(체크하면 되는 쪽이 안전하다)

GIVE_UP_TEXT = "날짜를 여러 번 여쭤봐도 정확히 알 수 없어서 등록하지 못했어요. 일정 등록 화면에서 직접 입력해 주세요"
DEFAULT_TITLES = {
    1: "약속",
    2: "할 일",
}  # 제목을 말하지 않았을 때(종류가 약속이면 약속, 아니면 할 일)
MAX_OVERLAPS = 3  # 겹침 안내에 보여 주는 일정 수
PRIVATE_ROOM_TEXT = "개인 일정으로 등록했어요."
AMBIGUOUS_TEXT = "날짜를 정확히 알려 주세요. 예: 10월 30일"
MEMBER_UNCLEAR_TEXT = "같은 호칭의 가족이 여러 명이에요. 누구인지 이름으로 알려 주세요"

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# 기간 모듈이 못 읽는 날짜 표현(N일·11/13·이틀 뒤 등). 근거 판단에만 쓴다
_DATE_HINT = re.compile(
    r"\d+\s*일|\d{1,2}\s*/\s*\d{1,2}|\d+\s*월|이틀|사흘|나흘|닷새|엿새|주\s*뒤|달\s*뒤"
)


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


def _int(value, low: int, high: int) -> int | None:
    """bool·비정수·범위 밖이면 None."""
    ok = isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
    return value if ok else None


def clean_rel(raw) -> dict:
    """모델이 돌려준 date_rel 을 정수 dict 로 검증한다. 없거나 형식이 틀리면 '상대 표현 없음' 기본값."""
    if not isinstance(raw, dict):
        return dict(NO_REL)
    weeks = _int(raw.get("weeks"), -MAX_REL_WEEKS, MAX_REL_WEEKS)
    days = _int(raw.get("days"), -DATE_SPAN_DAYS, DATE_SPAN_DAYS)
    weekday = _int(raw.get("weekday"), -1, 6)
    if weeks is None or days is None or weekday is None:
        return dict(NO_REL)
    return {"weeks": weeks, "days": days, "weekday": weekday}


def ungrounded(fields: dict, sentence: str, now: date) -> dict:
    """모델이 날짜를 적었는데 문장에 날짜·상대 표현이 전혀 없으면 그 날짜는 근거가 없다('저녁 8시에 가족 회의 잡아줘'에서 오늘로 정한 것 등).
    날짜는 임의로 정하지 않으므로 비워서 되묻게 한다. 상대 표현(date_rel)이 있으면 코드가 계산하므로 건드리지 않는다."""
    if not sentence or not fields.get("date") or has_rel(fields.get("date_rel")):
        return fields
    if period_mod.extract(sentence, now) is not None or _DATE_HINT.search(sentence):
        return fields
    return {**fields, "date": ""}


def has_rel(rel) -> bool:
    """date_rel 에 상대 표현이 들어 있는가(기본값이면 False)."""
    return isinstance(rel, dict) and clean_rel(rel) != NO_REL


def resolve_date(base: date, rel: dict) -> str:
    """상대 표현(weeks·days·weekday)을 base 기준 YYYY-MM-DD 로 계산한다. 범위 밖·형식 오류는 빈 문자열.
    weekday 가 -1 이면 base + weeks*7 + days(같은 요일 유지), 0~6 이면 base 가 속한 주의 월요일 + weeks*7 + weekday + days."""
    if not isinstance(rel, dict):
        return ""
    weeks = _int(rel.get("weeks"), -MAX_REL_WEEKS, MAX_REL_WEEKS)
    days = _int(rel.get("days"), -DATE_SPAN_DAYS, DATE_SPAN_DAYS)
    weekday = _int(rel.get("weekday"), -1, 6)
    if weeks is None or days is None or weekday is None:
        return ""
    anchor = (
        base if weekday == -1 else base - timedelta(days=base.weekday()) + timedelta(days=weekday)
    )
    try:
        result = anchor + timedelta(weeks=weeks, days=days)
    except OverflowError:
        return ""
    return valid_date(result.isoformat(), base)


def clean_fields(raw, member_ids: set[str]) -> dict:
    """모델이 돌려준 register 객체를 검증한다. 형식이 틀린 값은 빈 값으로 둔다(날짜 범위는 `normalize` 에서)."""
    if not isinstance(raw, dict):
        raw = {}
    kind = raw.get("kind")
    return {
        "title": _text(raw.get("title"), TITLE_MAX),
        "date": _text(raw.get("date"), 10),
        "date_rel": clean_rel(raw.get("date_rel")),
        "start_time": _text(raw.get("start_time"), 5),
        "end_time": _text(raw.get("end_time"), 5),
        "kind": kind if kind in (1, 2) and not isinstance(kind, bool) else 0,
        "place": _text(raw.get("place"), PLACE_MAX),
        "memo": _text(raw.get("memo"), MEMO_MAX),
        "share_ids": _ids(raw.get("share_ids"), member_ids),
        "date_ambiguous": raw.get("date_ambiguous") is True,
        "member_ambiguous": raw.get("member_ambiguous") is True,
        "time_assumed": raw.get("time_assumed") is True,  # 오전/오후를 모델이 정했다(안내에 밝힌다)
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


def _question(ambiguous: bool, reply: str) -> str:
    """되묻는 것은 날짜뿐이다(제목·시간은 모델이 정해 등록하고 안내에 밝힌다)."""
    if ambiguous:
        return reply or AMBIGUOUS_TEXT
    return "날짜가 빠졌어요. 언제로 등록할까요?"


def _hm(value: time | None) -> str:
    return f"{value:%H:%M}" if value else ""


def _to_time(value: str) -> time | None:
    return datetime.strptime(value, "%H:%M").time() if value else None


def _same_keywords(a: str, b: str) -> bool:
    """제목에서 뽑은 키워드(띄어쓰기 단위)가 한쪽이 다른 쪽에 모두 들어 있으면 같은 일정이다('하윤 치과' ↔ '하윤 치과 검진', 순서 무관)."""
    left, right = a.lower().split(), b.lower().split()
    if not left or not right:
        return False
    short, long_ = (left, right) if len(left) <= len(right) else (right, left)
    return all(any(k in w or w in k for w in long_) for k in short)


def _clock_text(value: str) -> str:
    """24시간 HH:MM 을 안내용 12시간 표기로: 14:00 → 오후 2시, 09:30 → 오전 9시 30분, 12:00 → 오후 12시."""
    moment = datetime.strptime(value, "%H:%M")
    half = "오전" if moment.hour < 12 else "오후"
    hour = moment.hour % 12 or 12
    minute = f" {moment.minute}분" if moment.minute else ""
    return f"{half} {hour}시{minute}"


def _ro(word: str) -> str:
    """조사만 돌려준다: '약속' → '으로', '할 일' → '로' (받침 ㄹ 은 '로')."""
    if not word:
        return "로"
    code = ord(word[-1]) - 0xAC00
    has_final = 0 <= code < 11172 and code % 28 != 0
    return "으로" if has_final and code % 28 != 8 else "로"


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _span(start: time, end: time | None) -> tuple[int, int]:
    """분 단위 구간. 끝이 없거나 시작보다 늦지 않으면 시작 + DEFAULT_MINUTES."""
    begin = _minutes(start)
    finish = _minutes(end) if end is not None else begin
    return begin, finish if finish > begin else begin + DEFAULT_MINUTES


def _overlaps(db: Session, user_id: str, group_id: str, event: Event) -> list[dict]:
    """같은 사람의 같은 날 일정 중 이 일정과 시간이 겹치는 것(최대 MAX_OVERLAPS 건, 시간순). 받은 복사본도 포함한다.
    양쪽 모두 시작 시간이 있을 때만 비교한다(시간 없는 일정은 겹침을 따지지 않는다)."""
    if event.start_time is None or event.start_date is None:
        return []
    mine = _span(event.start_time, event.end_time)
    query = (
        select(Event)
        .where(
            Event.group_id == group_id,
            Event.user_id == user_id,
            Event.deleted_at.is_(None),
            Event.start_date == event.start_date,
            Event.start_time.is_not(None),
            Event.id != event.id,
        )
        .order_by(Event.start_time, Event.title)
    )
    found: list[dict] = []
    for other in db.scalars(query):
        begin, finish = _span(other.start_time, other.end_time)
        if mine[0] < finish and begin < mine[1]:
            found.append({"title": other.title, "start_time": _hm(other.start_time)})
        if len(found) >= MAX_OVERLAPS:
            break
    return found


def notice_lines(data: dict) -> list[str]:
    """registered 카드 data 로 만드는 안내(추정한 제목·시간, 겹침). 등록 응답과 메인 경유 답이 같은 글을 쓴다."""
    lines: list[str] = []
    if data.get("title_assumed"):
        title = data.get("title", "")
        lines.append(f"제목을 말씀하지 않으셔서 '{title}'{_ro(title)} 등록했어요.")
    if data.get("time_assumed") and data.get("start_time"):
        clock = _clock_text(data["start_time"])
        lines.append(f"{clock}{_ro(clock)} 등록했어요(오전이면 말씀해 주세요).")
    overlaps = data.get("overlaps") or []
    if overlaps:
        named = ", ".join(f"{o['start_time']} {o['title']}" for o in overlaps)
        lines.append(f"{named} 일정과 시간이 겹쳐요.")
    return lines


def _existing(db: Session, user_id: str, group_id: str, draft: Draft) -> Event | None:
    """같은 사람이 같은 날짜에 이미 등록한 같은 일정(지운 것·받은 복사본 제외).
    제목의 키워드가 한쪽이 다른 쪽에 모두 들어 있고, 시작 시각이 같거나 한쪽이 비어 있으면 같은 일정으로 본다."""
    start = _to_time(draft.start_time)
    query = select(Event).where(
        Event.group_id == group_id,
        Event.user_id == user_id,
        Event.deleted_at.is_(None),
        Event.origin_id.is_(None),
        Event.start_date == date.fromisoformat(draft.date),
    )
    for event in db.scalars(query):
        if not _same_keywords(draft.title, event.title):
            continue
        if start is None or event.start_time is None or event.start_time == start:
            return event
    return None


def _created(
    db: Session,
    user_id: str,
    group_id: str,
    draft: Draft,
    members: list[Member],
    again: str = "same",
    title_assumed: bool = False,
    time_assumed: bool = False,
    check_overlaps: bool = True,
):
    """title_assumed·time_assumed: 제목·오전/오후를 모델·코드가 정했다(안내에 밝힌다). check_overlaps: 같은 날 시간이 겹치는 내 일정을 안내한다(가족방에서는 끈다).
    again: same 이면 같은 일정이 이미 있을 때 그 일정을 돌려주고(옛 앱의 확인), ask 이면 또 등록할지 되묻고, force 이면 그래도 등록한다."""
    # 같은 요청을 다시 보내거나 되묻는 답을 합쳐 다시 보내도 같은 일정이 두 번 생기지 않게 한다(공유 등록은 받는 사람 복사본이 있어 제외)
    already = (
        None if draft.share_ids or again == "force" else _existing(db, user_id, group_id, draft)
    )
    if already is not None and again == "ask":
        return AgentResponse(
            intent="register",
            text=f"{reader.event_text(already)} 일정은 이미 등록되어 있어요. 또 등록해 드릴까요?",
            choice=Choice(kind="register", changes=draft.model_dump()),
        )
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
    overlaps = [] if already or not check_overlaps else _overlaps(db, user_id, group_id, event)
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
            **({"title_assumed": True} if title_assumed and not already else {}),
            **({"time_assumed": True} if time_assumed and not already else {}),
            **({"overlaps": overlaps} if overlaps else {}),
        },
    )
    named = reader.event_text(event)
    labels = {m.id: m.label for m in members}
    who = ", ".join(labels[i] for i in draft.share_ids if i in labels)
    if already:
        text = f"{named} 일정이 이미 있어요."
    elif who:
        text = f"{named} 일정을 {who}님에게 공유해서 등록했어요."
    else:
        text = f"{named} 일정을 등록했어요."
    if not already:
        text = "\n".join([text, *notice_lines(card.data)])
    return AgentResponse(intent="register", text=text, cards=[card])


def respond(
    db: Session,
    user_id: str,
    group_id: str,
    request_draft: Draft | None,
    fields: dict,
    reply: str,
    members: list[Member],
    share_all: bool = False,
    sentence: str = "",
    private: bool = False,
    room: bool = False,
) -> AgentResponse:
    """private: '나만 보게' — 공유 대상을 비운다. room: 가족방 요청 — 겹침 안내를 끄고, private 이면 방에는 '개인 일정으로 등록했어요'만 쓴다."""
    member_ids = {m.id for m in members}
    fields = ungrounded(
        fields, sentence, today()
    )  # 문장에 근거 없는 날짜는 임의로 정하지 않고 되묻는다
    if not fields.get("date") and has_rel(
        fields.get("date_rel")
    ):  # 상대 표현은 코드가 오늘 기준으로 계산한다
        fields = {**fields, "date": resolve_date(today(), fields["date_rel"])}
    if private:  # 모델이 일부를 골라도 비운다(개인 우선)
        fields = {**fields, "share_ids": []}
        request_draft = (
            request_draft.model_copy(update={"share_ids": []}) if request_draft else None
        )
    elif share_all:  # 모델이 일부만 고르거나 비워 둬도 가족 전체로 정한다
        fields = {**fields, "share_ids": [m.id for m in members if m.id != user_id]}
    if fields.get("title") and fields.get("date"):
        request_draft = None  # 제목과 날짜를 모두 말한 문장은 새 요청이다: 옛 초안의 시간·장소·공유 대상이 섞이지 않게 한다
    draft = normalize(merge(request_draft, fields), member_ids, user_id, today())
    ambiguous = fields["date_ambiguous"]
    if ambiguous:
        draft = draft.model_copy(update={"date": ""})
    need_date = not draft.date
    who_unclear = fields[
        "member_ambiguous"
    ]  # 같은 호칭의 가족이 여럿이면 누구인지 먼저 되묻는다(정책 #33)
    if need_date or who_unclear:
        if draft.asks >= MAX_ASKS:
            return AgentResponse(intent="register", text=GIVE_UP_TEXT)
        asked = draft.model_copy(update={"asks": draft.asks + 1})
        text = (
            members_mod.ask_text(members, sentence, user_id, reply or MEMBER_UNCLEAR_TEXT)
            if who_unclear and not ambiguous
            else _question(ambiguous, reply)
        )
        return AgentResponse(intent="register", text=text, draft=asked)
    title_assumed = not draft.title  # 제목을 못 뽑았으면 되묻지 않고 기본 제목으로 등록한다
    if title_assumed:
        draft = draft.model_copy(update={"title": DEFAULT_TITLES.get(draft.kind, "할 일")})
    time_assumed = bool(fields.get("time_assumed")) and bool(draft.start_time)
    response = _created(  # 공유 등록도 카드 없이 바로 등록한다(정책 #32)
        db,
        user_id,
        group_id,
        draft,
        members,
        "ask",
        title_assumed,
        time_assumed,
        check_overlaps=not room,
    )
    if (
        not room and response.cards
    ):  # 방금 등록한 일정을 10분 기억한다(개인 채팅 전용: "엄마한테도 공유해줘")
        choice.remember_event(group_id, user_id, response.cards[0].data["event_id"])
    if room and private:  # 방 대화에는 개인 일정의 제목·날짜를 올리지 않는다
        response = response.model_copy(update={"text": PRIVATE_ROOM_TEXT})
    return response


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


def resolve_again(
    db: Session,
    user_id: str,
    group_id: str,
    asked: Choice,
    text: str,
    members: list[Member],
) -> AgentResponse | None:
    """ "이미 등록된 일정인데 또 등록해 드릴까요?"에 대한 답. 답으로 읽을 수 없으면 None(새 요청으로 본다)."""
    from .choice import NO_WORDS, YES_WORDS

    said = text.strip()
    if NO_WORDS.search(said):
        return AgentResponse(intent="register", text="알겠어요, 다시 등록하지 않았어요.")
    if not YES_WORDS.search(said):
        return None
    try:
        draft = Draft(**asked.changes)
    except ValueError:
        return None
    return _created(db, user_id, group_id, draft, members, "force")
