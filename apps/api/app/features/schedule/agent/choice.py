"""수정·삭제 대상이 하나로 정해지지 않을 때의 되묻기(정책 #29·#30·#33).

모델은 대상 하나만 고르고, 같은 제목의 일정이 더 있는지는 코드가 판단한다.
- 같은 제목이 하나뿐이거나 사용자가 그 일정의 날짜를 말했으면 그대로 처리한다.
- 과거와 미래가 섞여 있으면 지금 이후(미래) 하나만 대상으로 삼는다. 미래가 여럿이면 후보를 보여 주며 되묻는다.
- 삭제인데 미래 일정이 없고 지난 일정뿐이면 "지난 일정인데 맞나요?"라고 되묻는다.
되묻기에 대한 사용자의 답("12/3", "첫 번째", "모두", "응")은 서버가 기억한 후보와 대조해 읽는다(`pick`). 이 모듈은
저장소를 부르지 않는다(실행은 `modify.resolve_choice`)."""

import re
import threading
import time
from datetime import date

from . import reader
from .schemas import AgentResponse, Card, Choice

CHOICE_TTL_SECONDS = 600  # 되묻기를 기억하는 시간(등록 초안과 같다)

ALL_WORDS = re.compile(
    r"모두|전부|전체|둘 ?다|둘 ?모두|둘 ?똑같이|싹 ?다|다 (?:지워|삭제|옮겨|바꿔|수정)|^다$"
)
YES_WORDS = re.compile(r"^\s*(응|네|넵|예|어|그래|그렇|맞|좋아|ㅇㅇ|오케이|ok|확인)", re.IGNORECASE)
NO_WORDS = re.compile(r"아니|그만|말고|괜찮|하지 ?마|안 ?할래|됐어")
FIRST_WORDS = re.compile(r"첫|1 ?번|앞|처음|위")
SECOND_WORDS = re.compile(r"두 ?번째|둘째|2 ?번")
THIRD_WORDS = re.compile(r"세 ?번째|셋째|3 ?번")
LAST_WORDS = re.compile(r"마지막|뒤|나중|아래")
# 새 요청으로 보이는 말: 답("19일 걸로", "첫 번째", "모두", "응")에는 이런 동사가 없다. 있으면 새 요청으로 처리한다
NEW_REQUEST = re.compile(
    r"바꿔|바꾸|지워|지우|삭제|옮겨|미뤄|수정|등록|공유해|알려|보여|부탁|언제|뭐야|\?"
)
OWN_VERBS = {"edit": "바꿔|바꾸|수정|옮겨|미뤄", "delete": "지워|지우|삭제"}
MD = re.compile(r"(\d{1,2})\s*[/.월]\s*(\d{1,2})")
DAY_ONLY = re.compile(r"(?<![\d/.월])(\d{1,2})\s*일")


def event_day(event) -> date:
    return reader.to_local(event.starts_at).date()


def mentions(text: str, event) -> bool:
    """사용자의 말에 이 일정의 날짜(11/21, 11월 21일, 21일)가 들어 있는가."""
    return mentions_day(text, event_day(event))


def mentions_day(text: str, day: date) -> bool:
    for m in MD.finditer(text):
        if (int(m.group(1)), int(m.group(2))) == (day.month, day.day):
            return True
    return any(int(m.group(1)) == day.day for m in DAY_ONLY.finditer(text))


def narrow(target, events: dict, today: date, kind: str, text: str, related=()):
    """모델이 고른 대상을 같은 제목이거나 모델이 같은 일이라고 본(related: 제목에 같은 키워드가 있는 일정) 일정과 견줘 좁힌다. ("one", 일정) | ("ask", [일정…]) | ("past", [일정])."""
    same = sorted(
        (
            e
            for e in events.values()
            if e.id == target.id or e.id in related or e.title.strip() == target.title.strip()
        ),
        key=lambda e: reader.to_local(e.starts_at),
    )
    if len(same) <= 1 or mentions(text, target):
        return "one", target
    future = [e for e in same if event_day(e) >= today]
    if len(future) == 1:
        return "one", future[0]  # 과거와 미래가 섞여 있으면 미래 하나만 처리한다
    if len(future) > 1:
        return "ask", future
    if kind == "delete":  # 지난 일정뿐: 가장 최근 하나를 보여 주고 맞는지 묻는다
        return "past", [same[-1]]
    return "one", target


def ask_response(kind: str, found: list, changes: dict | None = None, past: bool = False):
    title = found[0].title
    if past:
        text = f"'{title}' 일정은 다가오는 게 없고 지난 일정뿐이에요. 이 일정이 맞나요?"
    else:
        text = f"'{title}' 일정이 {len(found)}개 있어요. 어느 쪽인가요? 모두인가요?"
    return AgentResponse(
        intent=kind,
        text=text,
        cards=[Card(type="event_list", data={"events": [reader.brief(e) for e in found]})],
        choice=Choice(kind=kind, event_ids=[e.id for e in found], changes=changes or {}, past=past),
    )


def ask_member(event, changes: dict, text: str) -> AgentResponse:
    """공유할 사람이 같은 호칭의 여럿이라 누구인지 되묻는다. 이미 정해진 사람(changes.share_ids)은 답을 받은 뒤 더한다."""
    return AgentResponse(
        intent="edit",
        text=text,
        choice=Choice(kind="edit", event_ids=[event.id], changes=changes, members=True),
    )


WHICH_LIMIT = 5  # 대상을 모를 때 보여 주는 후보 수(다가오는 일정 순)


def which_candidates(events: dict, today: date) -> list:
    """문장에 대상이 없을 때 보여 줄 일정: 다가오는 일정 먼저, 날짜 순으로 몇 개."""
    upcoming = [e for e in events.values() if event_day(e) >= today]
    upcoming.sort(key=lambda e: reader.to_local(e.starts_at))
    return upcoming[:WHICH_LIMIT]


def ask_which(kind: str, found: list, changes: dict | None = None) -> AgentResponse:
    """어느 일정을 말씀하시는지 후보를 보여 주며 되묻는다(정책 #35). 고르면 하려던 일을 이어서 처리한다."""
    return AgentResponse(
        intent=kind,
        text="어느 일정인가요?",
        cards=[Card(type="event_list", data={"events": [reader.brief(e) for e in found]})],
        choice=Choice(kind=kind, event_ids=[e.id for e in found], changes=changes or {}),
    )


def pick_members(text: str, members: list, me: str) -> list[str]:
    """되물음에 대한 답에서 이름이 들어 있는 가족(나 제외)의 id."""
    said = text.strip()
    if NEW_REQUEST.search(said):
        return []
    return [m.id for m in members if m.id != me and any(n and n in said for n in (m.label, m.name))]


def pick(text: str, choice: Choice, events: list) -> list[str] | None:
    """되묻기에 대한 답에서 고른 일정 id 들. 빈 목록이면 하지 않겠다는 답, None 이면 답으로 읽을 수 없다."""
    said = text.strip()
    if (
        NO_WORDS.search(said)
        and not NEW_REQUEST.search(said)
        and (choice.past or not mentions(said, events[0]))
    ):
        return []
    if NEW_REQUEST.search(said) and any(e.title.strip() and e.title.strip() in said for e in events):
        return None  # 일정 제목을 다시 말하며 시키는 말("헬스 다 지워줘")은 답이 아니라 새 요청이다
    own = OWN_VERBS.get(choice.kind, "")
    if ALL_WORDS.search(said) and not NEW_REQUEST.search(re.sub(own, "", said) if own else said):
        return [
            e.id for e in events
        ]  # "둘 다 바꿔줘"처럼 지금 하던 일의 동사만 붙은 답은 답으로 본다
    if NEW_REQUEST.search(said):
        return None
    if choice.past:
        if NO_WORDS.search(said):
            return []
        return [e.id for e in events] if YES_WORDS.search(said) else None
    if ALL_WORDS.search(said):
        return [e.id for e in events]
    by_date = [e.id for e in events if mentions(said, e)]
    if len(by_date) == 1:
        return by_date
    by_title = [e.id for e in events if e.title.strip() and e.title.strip() in said]
    if len(by_title) == 1:
        return by_title
    if THIRD_WORDS.search(said) and len(events) >= 3:
        return [events[2].id]
    if SECOND_WORDS.search(said) and len(events) >= 2:
        return [events[1].id]
    if LAST_WORDS.search(said):
        return [events[-1].id]
    if FIRST_WORDS.search(said):
        return [events[0].id]
    return None


_pending: dict[tuple[str, str], tuple[float, Choice]] = {}
_lock = threading.Lock()


def take(group_id: str, user_id: str) -> Choice | None:
    """이 사용자가 직전에 받은 되묻기(10분 안)를 꺼낸다. 프로세스 메모리라 재시작하면 사라진다."""
    now = time.monotonic()
    with _lock:
        for key in [k for k, (until, _) in _pending.items() if until <= now]:
            del _pending[key]
        item = _pending.pop((group_id, user_id), None)
    return item[1] if item else None


def keep(group_id: str, user_id: str, response: AgentResponse) -> None:
    if response.choice is not None:
        with _lock:
            _pending[(group_id, user_id)] = (
                time.monotonic() + CHOICE_TTL_SECONDS,
                response.choice,
            )
