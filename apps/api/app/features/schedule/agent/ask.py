"""메인 에이전트(가비 채팅)가 일정 요청을 넘길 때 쓰는 입구. 정산·돌봄 탭 에이전트의 `ask` 와 같은 모양이다.

메인이 `ask_schedule` 도구로 사용자의 일정 문장을 넘기면 `handler.handle` 에 그대로 보내고, 돌려받은 응답을 메인이 사용자에게
전할 글로 바꾼다. 일정 에이전트는 모델 호출을 메인 질문의 관문 한 번에 묶어 센다: 일정 에이전트는 이 입구에서 자기 관문(`ai_guard`, 일정 한도)을
다시 지나지 않고, 부른 횟수만 메인 질문의 사용 기록·한도에 더한다(정산·돌봄과 같다). 일정 탭 화면이 직접 부르는 입구는 예전처럼 일정 한도를 쓴다.

이 대화에서 하는 일: 조회와 등록(제목·날짜가 있으면 내 일정으로 바로 만들고, 없으면 되묻는다).
이 대화에서 하지 않는 일: 수정·삭제·가족에게 공유하는 등록은 확인 카드가 필요해서 실행하지 않고 일정 화면으로 안내한다.
되묻는 초안은 서버가 사용자별로 10분 기억하고(`_take_draft`), 메인도 앞 대화를 합쳐 완전한 문장으로 다시 넘긴다. 제목과 날짜를 모두 말한 문장은 새 요청으로 보고 옛 초안을 쓰지 않는다."""

import re
import threading
import time

from sqlalchemy.orm import Session

from app.features.family_group.models import User
from app.shared.llm.agent import AgentReply, Post

from . import handler
from . import members as members_mod
from .schemas import AgentRequest, AgentResponse, Draft

DESCRIPTION = (
    "일정 탭 담당. 일정 탭에 이미 입력된 내 일정을 조회하고, 사용자가 일정에 넣어 달라고 분명히 말한 새 일정을 등록한다. "
    "제목과 날짜가 있으면 바로 등록하고, 빠졌으면 되묻는 질문을 돌려준다. "
    "올려 둔 문서(학교 안내문·항공권·예약 확인서 등)에 적힌 날짜는 알지 못하니 그런 질문에는 쓰지 않는다. "
    "일정 수정·삭제와 다른 가족에게 공유해서 등록하는 것은 사용자 화면에 확인 카드가 나타나고 버튼을 눌러야 반영된다. "
    "가족에게 일을 같이 해 달라고 보내는 부탁(함께하기)도 맡는다: 부탁 보내기·받는 사람 바꾸기·취소는 확인 카드가 나타나고 버튼을 눌러야 "
    "반영되며, 보낸·받은 부탁의 상세와 수락 현황 질문은 바로 답한다. '엄마한테 내일 3시에 장 같이 봐달라고 부탁해줘'처럼 "
    "누구에게·무엇을·언제를 담은 완전한 문장으로 넘긴다. "
    "'가족 모두에게 공유'도 그대로 넘긴다. "
    "'내일 오후 3시 엄마 생신 일정으로 등록해줘'처럼 날짜·시간 표현과 제목을 담은 완전한 문장으로 넘긴다. "
    "한 번에 일정 하나만 등록하니, 여러 개를 넣으려면 일정마다 따로 부른다."
)

CARD_SHOWN = "아직 실행되지 않았어요. 사용자 화면에 확인 카드가 나타났고, 사용자가 카드의 버튼을 눌러야 반영돼요."
ASK_BACK = "일정을 등록하려면 정보가 더 필요해요. 사용자에게 이 질문을 그대로 전하세요. 답을 받으면 날짜·시간·제목을 합친 완전한 문장으로 다시 넘기세요: "
NOT_SCHEDULE = "일정과 관련된 요청이 아니에요."
MAX_EVENTS_SHOWN = 10


def _event_line(event: dict) -> str:
    # 등록 카드는 start_time, 목록 카드(brief)는 time 이라는 이름을 쓴다
    clock = event.get("start_time") or event.get("time") or ""
    when = " ".join(x for x in (event.get("date", ""), clock) if x)
    return f"- {when} {event.get('title', '')}".strip()


def _request_summary(brief: dict) -> str:
    """부탁 목록 카드 한 줄: 날짜 시간 제목 — 받는 분과 수락 현황(보낸 사람) 또는 보낸이와 수락한 사람(받은 사람)."""
    head = _event_line(brief)
    if brief.get("role") == "sent":
        who = ", ".join(f"{r['name']}({r['status']})" for r in brief.get("recipients", []))
        return f"{head} — 받는 분: {who}" if who else head
    tail = f" — 보낸 분: {brief.get('from', '')}"
    if brief.get("accepted"):
        tail += f", 수락: {', '.join(brief['accepted'])}"
    return head + tail


WHOLE_FAMILY = re.compile(
    r"가족\s*(모두|전체|전원|다)|온\s*가족|식구\s*(모두|전체)|다\s*같이|모두에게|모두한테"
)


def wants_whole_family(text: str) -> bool:
    return "공유" in text and bool(WHOLE_FAMILY.search(text))


def with_whole_family(text: str, db: Session, group_id: str, user_id: str) -> str:
    """'가족 모두에게 공유해서'처럼 가족 전체를 말하면 공유 대상 이름을 질문 뒤에 밝혀 넘긴다. 모델이 일부만 고르는 일을 막는다.
    말한 사람(나)은 뺀다(코드가 어차피 자기 자신에게는 공유하지 않는다)."""
    if not wants_whole_family(text):
        return text
    others = [m.label for m in members_mod.load(db, group_id) if m.id != user_id]
    return f"{text} (공유 대상: {', '.join(others)})" if others else text


def _change_line(change) -> str:
    """수정 카드의 바뀌는 내용 한 줄. 일정 에이전트는 {label, before, after} 로 준다."""
    if isinstance(change, dict):
        return f"{change.get('label', '')}: {change.get('before', '')} → {change.get('after', '')}"
    return str(change)


def _request_lines(action, data: dict) -> tuple[list[str], list[str]]:
    """부탁 확인 카드의 (줄들, 받는 사람 이름들)."""
    kind = data.get("action")
    if kind == "create":
        lines = [_event_line(data).removeprefix("- ")]
        if data.get("place"):
            lines.append(f"장소 {data['place']}")
        who = [w["name"] for w in data.get("to", [])]
        return lines, who
    brief = data.get("request", {})
    lines = [_event_line(brief).removeprefix("- ")]
    lines.extend(_change_line(x) for x in data.get("changes", []))
    return lines, []


def _confirmation(response: AgentResponse) -> dict:
    """앱이 그리는 확인 카드. pending_action 은 버튼을 누를 때 그대로 돌려받아 서버가 처음부터 다시 검증한다."""
    action = response.pending_action
    card = next((c for c in response.cards if c.type.endswith("_confirm")), None)
    data = card.data if card else {}
    lines: list[str] = []
    shared: list[str] = []
    if action.type.startswith("request_"):
        lines, shared = _request_lines(action, data)
    elif action.type == "register":
        lines.append(_event_line(data).removeprefix("- "))
        if data.get("place"):
            lines.append(f"장소 {data['place']}")
        shared = [w["name"] for w in data.get("share", [])]
    else:
        event = data.get("event", {})
        lines.append(_event_line(event).removeprefix("- "))
        lines.extend(_change_line(x) for x in data.get("changes", []))
    return {
        "kind": "schedule",
        "action": action.type,
        "title": response.text,
        "lines": [x for x in lines if x],
        "shared_with": shared,
        "pending_action": action.model_dump(mode="json"),
    }


PENDING_TTL_SECONDS = 600  # 되묻는 초안을 기억하는 시간
_pending: dict[tuple[str, str], tuple[float, Draft]] = {}
_pending_lock = threading.Lock()


def _take_draft(group_id: str, user_id: str) -> Draft | None:
    """이 사용자가 직전에 되물음을 받은 초안이 있으면(10분 안) 꺼낸다. 프로세스 메모리라 재시작하면 사라진다(그러면 메인이 합쳐 준 문장으로 처리한다)."""
    now = time.monotonic()
    with _pending_lock:
        for key in [k for k, (until, _) in _pending.items() if until <= now]:
            del _pending[key]
        item = _pending.pop((group_id, user_id), None)
    return item[1] if item else None


def _keep_draft(group_id: str, user_id: str, response: AgentResponse) -> None:
    if response.draft is not None:
        with _pending_lock:
            _pending[(group_id, user_id)] = (
                time.monotonic() + PENDING_TTL_SECONDS,
                response.draft,
            )


def _reply(response: AgentResponse) -> AgentReply:
    """일정 에이전트의 응답을 메인이 사용자에게 전할 글로 바꾼다. 실행되지 않은 일을 실행됐다고 말하게 하지 않는다."""
    if response.intent == "not_schedule":
        return AgentReply(NOT_SCHEDULE, can_answer=False)
    if (
        response.pending_action is not None
    ):  # 공유 등록·수정·삭제: 앱이 확인 카드로 보여 주고 버튼으로 실행한다
        card = _confirmation(response)
        return AgentReply(
            f"{CARD_SHOWN} ({card['title']})", confirmations=[card], user_text=card["title"]
        )
    if response.draft is not None:  # 제목이나 날짜가 빠져 되묻는 중
        return AgentReply(f"{ASK_BACK}{response.text}", user_text=response.text)
    registered = next((c for c in response.cards if c.type == "registered"), None)
    if registered is not None:
        line = _event_line(registered.data)
        head = (
            "이미 같은 일정이 있어요." if registered.data.get("already") else "일정을 등록했어요."
        )
        text = f"{head}\n{line}"
        return AgentReply(text, user_text=text)
    asked = next((c for c in response.cards if c.type == "request_list"), None)
    listed = next((c for c in response.cards if c.type == "event_list"), None)
    if asked is not None or listed is not None:  # 일정 질의에는 일정 줄과 부탁 줄이 함께 올 수 있다
        events = listed.data.get("events", [])[:MAX_EVENTS_SHOWN] if listed else []
        requests_ = asked.data.get("requests", [])[:MAX_EVENTS_SHOWN] if asked else []
        lines = "\n".join(
            [*(_event_line(e) for e in events), *(_request_summary(r) for r in requests_)]
        )
        text = f"{response.text}\n{lines}".strip()
        return AgentReply(text, user_text=text)
    if response.text:
        return AgentReply(response.text, user_text=response.text)
    return AgentReply("이 요청은 아직 처리할 수 없어요.", can_answer=False)


def ask(
    db: Session,
    group_id: str,
    user: User,
    question: str,
    post: Post | None = None,
    history: list[dict] | None = None,
    guarded: bool = False,
) -> AgentReply:
    """`post`·`history` 는 정산·돌봄 에이전트와 호출 모양을 맞추는 자리다(쓰지 않는다). `guarded=False`(메인 채팅 안)이면 자기 관문을 다시 지나지 않는다."""
    text = with_whole_family(question.strip(), db, group_id, user.id)
    request = AgentRequest(
        text=text[:2000], channel="personal", draft=_take_draft(group_id, user.id)
    )
    response = handler.handle(
        db, user.id, group_id, request, share_all=wants_whole_family(question), guarded=guarded
    )
    _keep_draft(group_id, user.id, response)
    return _reply(response)
