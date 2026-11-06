"""먼저 챙겨주기: 올린 문서의 날짜에서 챙길 일을 뽑고, 앱을 열 때 먼저 말을 건다(docs/features/ai_assistant-reminders.md).

흐름
  ① 업로드가 저장되면 `plan` 이 문서에서 이미 찾은 날짜 중 챙길 일이 있는 것만 Claude 로 고른다(급함·며칠 전부터 포함).
     일정 표(events)는 건드리지 않고 `document_reminders` 에 "일정으로 잡을지 물을 대상"으로 둔다.
  ② 앱을 열 때 `due_nudges` 가 지금 말할 것을 돌려준다:
     - 일정에 넣어 드릴까요?  (아직 일정에 없는 문서 날짜, 하루 한 번씩 최대 3번)
     - 급한 일 미리 알림   (일정 시각 기준 24시간 단위. 하루 전이면 24시간 전, 이틀 전이면 48시간 전·24시간 전)
     - 지난 일 확인        (일정 날짜가 지났는데 체크가 안 되어 있으면 한 번: 하셨나요?)
  ③ 사용자의 답은 채팅에서 `resolve` 가 반영한다(일정으로 잡기·했어요·오늘로 다시 잡기·그만 알리기).
사람마다 스위치(`ReminderSetting`)로 끌 수 있고, 꺼져 있으면 아무것도 말하지 않고 새로 뽑지도 않는다.
문구는 고정 템플릿이며 일 이름(문서에서 이름·번호를 뺀 짧은 말)만 들어간다.
"""

import logging
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.schedule import repository as schedule_repo
from app.features.schedule import service as schedule_service
from app.features.schedule.models import Event
from app.features.schedule.schemas import EventCreate
from app.shared.config import settings
from app.shared.errors import not_found
from app.shared.llm import doc_ai

from . import family_names
from .knowledge.repository import get_item
from .models import DocumentReminder, ReminderSetting

logger = logging.getLogger(__name__)

DATE_LINE = re.compile(r"^- 날짜: (.+)$", re.MULTILINE)
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
BRACKETS = re.compile(r"\[[^\]]*\]")
DEFAULT_TIME = time(9, 0)  # 시각이 없는 일정은 그날 아침 9시로 센다
MAX_PER_ITEM = 3
MAX_PROPOSAL_ASKS = 3
MAX_LEAD_DAYS = 3
GENERIC_WORDS = frozenset({"제출", "확인", "안내", "참가", "일정", "신청", "접수", "준비"})
BODY_LIMIT = 6000
PLACE_LIMIT = 100
MEMO_LIMIT = 200
PREP_LIMIT = 120
DEFAULT_MEMO = "올려 주신 문서에서 가져왔어요"
ACTIONS = ("schedule", "done", "prepared", "redo_today", "dismiss")
WEEKDAYS = "월화수목금토일"


def _tz() -> timezone:
    return timezone(timedelta(hours=settings.ai_day_utc_offset_hours))


def _local(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(_tz())


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------- 스위치 ----------
def is_enabled(db: Session, user_id: str) -> bool:
    row = db.get(ReminderSetting, user_id)
    return row is None or row.enabled


def set_enabled(db: Session, user_id: str, enabled: bool) -> bool:
    row = db.get(ReminderSetting, user_id)
    if row is None:
        row = ReminderSetting(user_id=user_id)
        db.add(row)
    row.enabled = enabled
    row.updated_at = datetime.now(UTC)
    db.commit()
    return enabled


# ---------- ① 뽑기 ----------
def _clean_label(label: str) -> str:
    """일 이름에서 [..] 표시(가족·가린 값)를 빼고 120자로 줄인다."""
    return " ".join(BRACKETS.sub(" ", label).split())[:120]


def _clean_text(text: str, limit: int) -> str:
    """장소·메모에서 [..] 표시를 빼고 한 줄로 줄인다. 다 빠져 비면 빈 문자열."""
    return " ".join(BRACKETS.sub(" ", text or "").split())[:limit]


def _parse_time(value: str) -> time | None:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", value or "")
    return time(int(m.group(1)), int(m.group(2))) if m else None


def _candidate_dates(body: str, today: date) -> list[date]:
    out: list[date] = []
    for line in DATE_LINE.findall(body):
        for raw in ISO_DATE.findall(line):
            try:
                d = date.fromisoformat(raw)
            except ValueError:
                continue
            if d >= today and d not in out:
                out.append(d)
    return out


def plan(
    db: Session, group_id: str, uploader_id: str, item_id: str, now: datetime | None = None
) -> int:
    """기록 하나에서 챙길 일을 뽑아 저장한다. 저장한 개수를 돌려준다. 호출이 실패하면 LLMUnavailable 이 올라간다."""
    item = get_item(db, group_id, item_id)
    if item is None:
        return 0
    today = _local(now).date()
    dates = _candidate_dates(item.body_md, today)
    if not dates:
        return 0
    tagged = family_names.extract_ids(item.body_md)
    owner = tagged[0] if len(tagged) == 1 else uploader_id
    if not is_enabled(db, owner):
        return 0
    found = doc_ai.plan_reminders(
        item.title,
        item.body_md[:BODY_LIMIT],
        [d.isoformat() for d in dates],
        today.isoformat(),
    )
    have = {
        (r.due_date, r.title)
        for r in db.scalars(
            select(DocumentReminder).where(
                DocumentReminder.item_id == item.id, DocumentReminder.user_id == owner
            )
        )
    }
    saved = 0
    for p in found:
        if saved >= MAX_PER_ITEM:
            break
        try:
            due = date.fromisoformat(p.date)
        except ValueError:
            continue
        label = _clean_label(p.label)
        if due not in dates or not label or (due, label) in have:
            continue  # 문서에서 찾지 않은 날짜는 믿지 않는다
        lead = min(max(p.lead_days, 1), MAX_LEAD_DAYS) if p.urgent else 0
        db.add(
            DocumentReminder(
                id=_new_id(),
                group_id=group_id,
                user_id=owner,
                item_id=item.id,
                title=label,
                due_date=due,
                due_time=_parse_time(p.time),
                urgent=p.urgent,
                lead_days=lead,
                place=_clean_text(p.place, PLACE_LIMIT),
                memo=_clean_text(p.memo, MEMO_LIMIT),
                prep=_clean_text(p.prep, PREP_LIMIT),
            )
        )
        have.add((due, label))
        saved += 1
    db.commit()
    return saved


# ---------- ② 앱을 열 때 말할 것 ----------
RELATIVE_DAYS = {0: "오늘", 1: "내일", 2: "모레"}


def _josa(word: str, with_final: str, without_final: str) -> str:
    """마지막 글자의 받침에 맞는 조사(은/는, 이/가, 을/를). 한글이 아니면 받침 없는 쪽."""
    last = word.strip()[-1:]
    if "가" <= last <= "힣":
        return with_final if (ord(last) - 0xAC00) % 28 else without_final
    return without_final


def _prep_sentence(prep: str) -> str:
    """ "준비물은 도시락, 물이에요." 처럼 준비물 문장(없으면 빈 문자열)."""
    return f"준비물은 **{prep}**{_josa(prep, '이에요', '예요')}." if prep else ""


def _event_memo(r: DocumentReminder) -> str:
    """일정 메모: 문서 핵심 내용에 준비물이 빠져 있으면 덧붙인다."""
    memo = r.memo
    if r.prep and r.prep not in memo:
        memo = f"{memo} 준비물: {r.prep}".strip()
    return memo


def _clock(at: time) -> str:
    hour = at.hour % 12 or 12
    return f"{'오전' if at.hour < 12 else '오후'} {hour}시" + (
        f" {at.minute}분" if at.minute else ""
    )


def _when_text(due: date, at: time | None, today: date | None = None) -> str:
    """ "내일(11월 7일) 오전 8시 40분"처럼 말한다. 오늘·내일·모레가 아니면 "11월 7일(토)"."""
    day = f"{due.month}월 {due.day}일"
    gap = (due - today).days if today else None
    text = (
        f"{RELATIVE_DAYS[gap]}({day})"
        if gap in RELATIVE_DAYS
        else f"{day}({WEEKDAYS[due.weekday()]})"
    )
    return text + (f" {_clock(at)}" if at else "")


def _start_of(row: DocumentReminder, event) -> datetime:
    day = event.start_date or row.due_date
    at = event.start_time or row.due_time or DEFAULT_TIME
    return datetime.combine(day, at, tzinfo=_tz())


def _words(text: str) -> set[str]:
    """일 이름·일정 제목에서 겹침을 볼 낱말(두 글자 이상, 어느 일에나 붙는 말은 뺀다)."""
    return {w for w in re.findall(r"[0-9A-Za-z가-힣]{2,}", text) if w not in GENERIC_WORDS}


def _match_score(r: DocumentReminder, e: Event) -> int:
    """같은 일일 가능성: 이름이 겹치는 낱말 수(+같은 시각이면 1). 0 이면 다른 일로 본다.
    같은 날 항목이 여럿이어도 날짜만으로 같은 일로 묶지 않는다."""
    score = len(_words(r.title) & _words(e.title))
    if r.due_time is not None and e.start_time == r.due_time:
        score += 1
    return score


def _already_scheduled(db: Session, r: DocumentReminder) -> Event | None:
    """같은 날짜로 이미 내 일정에 있는 같은 일(문서를 올리기 전이든 뒤든, 이름이나 시각이 맞는 것). 다른 챙길 일이 이미 쓴 일정은 뺀다."""
    taken = set(
        db.scalars(
            select(DocumentReminder.event_id).where(
                DocumentReminder.event_id.is_not(None), DocumentReminder.id != r.id
            )
        )
    )
    events = db.scalars(
        select(Event)
        .where(
            Event.user_id == r.user_id,
            Event.group_id == r.group_id,
            Event.start_date == r.due_date,
            Event.deleted_at.is_(None),
        )
        .order_by(Event.created_at)
    ).all()
    scored = [(_match_score(r, e), e) for e in events if e.id not in taken]
    best = max(scored, key=lambda s: s[0], default=(0, None))
    return best[1] if best[0] > 0 else None


def due_nudges(db: Session, group_id: str, user_id: str, now: datetime | None = None) -> list[dict]:
    """지금 사용자에게 먼저 할 말. 한 번 돌려준 것은 다시 돌려주지 않도록 상태를 남긴다."""
    if not is_enabled(db, user_id):
        return []
    here = _local(now)
    today = here.date()
    rows = db.scalars(
        select(DocumentReminder)
        .where(
            DocumentReminder.group_id == group_id,
            DocumentReminder.user_id == user_id,
            DocumentReminder.status.in_(("proposed", "scheduled")),
        )
        .order_by(DocumentReminder.due_date, DocumentReminder.created_at)
    ).all()
    out: list[dict] = []
    for r in rows:
        if r.status == "proposed":
            ev = _already_scheduled(db, r)
            if (
                ev is not None
            ):  # 업로드 직후 카드로 이미 일정에 넣었다: 다시 묻지 않고 그 일정을 이어서 챙긴다
                r.event_id, r.status = ev.id, "scheduled"
        if r.status == "proposed":
            if r.due_date < today:
                r.status = "dismissed"  # 물어보지 못한 채 날짜가 지났다
            elif r.asked_count < MAX_PROPOSAL_ASKS and r.last_asked_on != today:
                r.asked_count += 1
                r.last_asked_on = today
                out.append(
                    {
                        "id": r.id,
                        "kind": "propose",
                        "title": r.title,
                        "when": _when_text(r.due_date, r.due_time, today),
                        "place": r.place,
                        "prep": r.prep,
                        "at": datetime.combine(r.due_date, r.due_time or time(0, 0)).isoformat(),
                        "text": (
                            f"올려 주신 문서에서 {_when_text(r.due_date, r.due_time, today)} "
                            f"‘{r.title}’{_josa(r.title, '을', '를')} 찾았어요. "
                            + (_prep_sentence(r.prep) + " " if r.prep else "")
                            + "일정에 넣어 드릴까요?"
                        ),
                    }
                )
            continue
        event = schedule_repo.get(db, group_id, r.event_id, user_id) if r.event_id else None
        if event is None:  # 일정을 지웠다
            r.status = "dismissed"
            continue
        if event.checked:
            r.status = "done"
            continue
        if (
            r.last_asked_on == today
        ):  # 오늘 이미 말했거나 사용자가 답했다: 같은 일은 하루에 한 번만 챙긴다
            continue
        start = _start_of(r, event)
        if here < start:
            if not r.urgent:
                continue
            hours_left = (start - here).total_seconds() / 3600
            slots = [
                h
                for h in range(24 * r.lead_days, 0, -24)
                if hours_left <= h and (r.asked_hours is None or h < r.asked_hours)
            ]
            if slots:
                r.asked_hours = min(slots)
                r.last_asked_on = today
                out.append(
                    {
                        "id": r.id,
                        "kind": "urgent",
                        "title": r.title,
                        "when": _when_text(start.date(), event.start_time, today),
                        "place": event.place or r.place,
                        "prep": r.prep,
                        "hours": max(1, round(hours_left)),
                        "at": start.replace(tzinfo=None).isoformat(),
                        "text": (
                            f"{_when_text(start.date(), event.start_time, today)}에 "
                            f"‘{r.title}’{_josa(r.title, '이', '가')} 있어요. "
                            + (_prep_sentence(r.prep) + " " if r.prep else "")
                            + f"약 {max(1, round(hours_left))}시간 남았는데, "
                            + ("준비물은 다 챙기셨나요?" if r.prep else "준비는 되셨나요?")
                        ),
                    }
                )
        elif start.date() < today and r.followup_asked_on is None:
            r.followup_asked_on = today
            r.last_asked_on = today
            out.append(
                {
                    "id": r.id,
                    "kind": "followup",
                    "title": r.title,
                    "when": f"{start.month}월 {start.day}일",
                    "place": "",
                    "prep": "",
                    "at": start.replace(tzinfo=None).isoformat(),
                    "text": (
                        f"{start.month}월 {start.day}일 ‘{r.title}’{_josa(r.title, '은', '는')} 하셨나요? "
                        "아직 체크가 안 돼 있어서 여쭤봐요."
                    ),
                }
            )
    db.commit()
    return out


SECTIONS = (  # (종류, 제목) — 급한 것부터 보여 준다
    ("urgent", "곧 다가오는 일정이에요"),
    ("followup", "지난 일정 중에 아직 체크가 안 된 게 있어요"),
    ("propose", "올려 주신 문서에서 이런 일정을 찾았어요"),
)


def _item_block(n: dict) -> list[str]:
    """한 건을 문서처럼: 굵은 제목 줄 아래에 일시·장소·준비물·남은 시간을 불릿으로(말풍선은 한 단계 목록만 보여 준다)."""
    lines = [f"**{n['title']}**", f"- 일시: {n['when']}"]
    if n.get("place"):
        lines.append(f"- 장소: {n['place']}")
    if n.get("prep"):
        lines.append(f"- 준비물: **{n['prep']}**")
    if n.get("hours"):
        lines.append(f"- 남은 시간: 약 {n['hours']}시간")
    return lines


def _closing(kind: str, items: list[dict]) -> str:
    """종류마다 끝에 붙는 한 줄 질문."""
    if kind == "urgent":
        return (
            "준비물은 다 챙기셨나요?" if any(n.get("prep") for n in items) else "준비는 되셨나요?"
        )
    if kind == "followup":
        return '하셨나요? 하신 건 "했어"라고 말씀해 주세요.'
    return '일정에 넣어 드릴까요? "다 넣어줘"나 "첫 번째만 넣어줘"처럼 말씀해 주세요.'


def compose(nudges: list[dict]) -> str:
    """한 번에 말할 것들을 문서처럼 정리한 한 덩어리(채팅 말풍선의 ## 제목·- 목록·**굵게** 서식)로 묶는다.
    종류마다 제목 아래에 건별로 굵은 제목과 불릿(시각 순)을 두고 한 줄 질문으로 끝낸다.
    하나뿐이면 그 문장 그대로, 없으면 빈 문자열."""
    if not nudges:
        return ""
    if len(nudges) == 1:
        return nudges[0]["text"]
    lines = [f"확인해 드릴 게 {len(nudges)}가지 있어요."]
    for kind, heading in SECTIONS:
        items = sorted((n for n in nudges if n["kind"] == kind), key=lambda n: n.get("at", ""))
        if items:
            lines.append(f"## {heading}")
            for n in items:
                lines += _item_block(n)
            lines.append(_closing(kind, items))
    return "\n".join(lines)


def pending_for_chat(
    db: Session, group_id: str, user_id: str, now: datetime | None = None
) -> list[DocumentReminder]:
    """사용자가 채팅에서 답할 수 있는, 최근에 물어본 챙길 일(모델이 resolve_reminder 로 처리한다)."""
    if not is_enabled(db, user_id):
        return []
    today = _local(now).date()
    since = today - timedelta(days=3)
    rows = db.scalars(
        select(DocumentReminder).where(
            DocumentReminder.group_id == group_id,
            DocumentReminder.user_id == user_id,
            DocumentReminder.status.in_(("proposed", "scheduled")),
        )
    ).all()
    return [
        r
        for r in rows
        if (r.status == "proposed" and r.last_asked_on and r.last_asked_on >= since)
        or (r.status == "scheduled" and r.followup_asked_on and r.followup_asked_on >= since)
        or (r.status == "scheduled" and r.asked_hours is not None and r.due_date >= since)
    ]


def note_lines(rows: list[DocumentReminder]) -> str:
    """시스템 안내에 붙일 줄: id | 일 이름 | 날짜 | 지금 묻는 내용."""
    ask = {
        "proposed": "일정으로 잡을지 물어봄",
        "scheduled": "미리 알림/했는지 물어봄",
    }
    return "\n".join(
        f"- {r.id} | {r.title} | {r.due_date.isoformat()} | {ask[r.status]}" for r in rows
    )


# ---------- ③ 답 반영 ----------
def resolve(
    db: Session,
    group_id: str,
    user_id: str,
    reminder_id: str,
    action: str,
    now: datetime | None = None,
) -> dict:
    """사용자의 답을 반영한다. action: schedule(일정으로 잡기) · done(했어요) · prepared(준비물·준비를 다 챙겼어요, 일정은 아직 안 끝남) · redo_today(오늘 일정으로 다시 잡기) · dismiss(그만 알리기)."""
    if action not in ACTIONS:
        raise ValueError(f"action 은 {', '.join(ACTIONS)} 중 하나여야 해요")
    r = db.scalar(
        select(DocumentReminder).where(
            DocumentReminder.id == reminder_id,
            DocumentReminder.group_id == group_id,
            DocumentReminder.user_id == user_id,
        )
    )
    if r is None:
        raise not_found("챙길 일")
    if r.status in ("done", "dismissed"):
        return {"ok": True, "status": r.status, "message": "이미 정리된 일이에요"}
    today = _local(now).date()
    if action == "schedule":
        if r.status != "proposed":
            return {"ok": True, "status": r.status, "message": "이미 일정에 있어요"}
        r.event_id = _create_event(
            db, group_id, user_id, r.title, r.due_date, r.due_time, r.place, _event_memo(r)
        ).id
        r.status = "scheduled"
    elif action == "done":
        if r.event_id:
            schedule_service.set_checked(db, group_id, user_id, r.event_id, True)
        r.status = "done"
    elif action == "prepared":
        r.urgent, r.lead_days = (
            False,
            0,
        )  # 챙겼다니 미리 알림은 그만하고, 일정이 지난 뒤 확인만 남긴다
    elif action == "redo_today":
        r.event_id = _create_event(
            db, group_id, user_id, r.title, today, None, r.place, _event_memo(r)
        ).id
        r.due_date, r.due_time = today, None
        r.urgent, r.lead_days, r.asked_hours, r.followup_asked_on = False, 0, None, None
        r.status = "scheduled"
    else:
        r.status = "dismissed"
    r.last_asked_on = today  # 답을 받은 날은 같은 일을 더 묻지 않는다
    db.commit()
    return {"ok": True, "status": r.status, "title": r.title, "date": r.due_date.isoformat()}


def _create_event(
    db: Session,
    group_id: str,
    user_id: str,
    title: str,
    day: date,
    at: time | None,
    place: str = "",
    memo: str = "",
):
    return schedule_service.create(
        db,
        group_id,
        user_id,
        EventCreate(
            title=title,
            start_date=day,
            start_time=at,
            kind=1 if at else 2,  # 시각이 있으면 약속, 없으면 할 일
            source="photo",
            place=place,
            memo=memo or DEFAULT_MEMO,
        ),
    )
