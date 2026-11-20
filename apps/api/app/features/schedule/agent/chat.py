"""사용자 문장을 한 번의 LLM 호출로 분류하고 답까지 받는다(질문 1회 = 호출 1회). 호출은 공통 관문 `ai_guard.run` 을 거친다.

분류만 따로 하지 않는다: 코드는 돌려받은 intent 로 종류별 처리(확인 카드·권한 검사 등)를 정하고, 모델 출력은 그대로 믿지 않고 검증한다.
외부로 나가기 전에 개인정보를 가린다: 사용자 문장·등록 초안·구성원은 공통 가명화 모듈(`app/shared/privacy`)로 토큰으로 바꿔 보내고,
모델이 돌려준 글자는 같은 요청의 대응표로 복원한다(등록한 제목에 전화번호가 있어도 저장되는 값은 원래 값이다).
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

# ai_assistant 기능 폴더의 app/features/ai_assistant/ingest/masking.py 에서 mask_text 함수 하나를 가져다 쓴다.
# 일정 목록의 제목(여러 줄, 복원할 일 없음)에서 주민번호·전화·카드·이메일·계좌·라벨 있는 이름·주소를 가린다.
# 이 함수의 위치나 이름을 바꾸면 여기도 고쳐야 한다.
from app.features.ai_assistant.ingest.masking import mask_text
from app.shared import ai_guard
from app.shared.errors import ApiError, bad_request
from app.shared.llm import client as llm
from app.shared.llm import eval_hook
from app.shared.privacy import Action, Kind, Policy, Row, prepare_transcript, restore_json

from . import habits, limits, modify, prompts, register, request_flow  # noqa: F401  (limits: 일정 호출 한도를 따로 세도록 등록)
from .members import Member, line, names
from .schemas import INTENTS, Draft, Intent

FEATURE = "schedule_chat"
MAX_REPLY_CHARS = 600
MAX_EVENT_IDS = 20
MAX_KEYWORD_CHARS = 30

# 사용자 문장·초안·구성원에 든 개인정보를 가려 보내고(PERSON·ADDRESS·PHONE·EMAIL), 주민번호·카드·계좌 같은 것이 있으면 보내지 않는다.
# 일정을 등록하면 사용자가 말한 값이 그대로 저장돼야 하므로 가린 값 네 종류는 응답에서 원래 값으로 복원한다.
POLICY = Policy(
    "schedule",
    {
        Kind.PHONE: Action.MASK,
        Kind.EMAIL: Action.MASK,
        Kind.ADDRESS: Action.MASK,
        Kind.PERSON: Action.MASK,
        Kind.ACCOUNT: Action.BLOCK,
        Kind.SECRET: Action.BLOCK,
        Kind.RRN: Action.BLOCK,
        Kind.CARD: Action.BLOCK,
    },
    restore_kinds=frozenset({Kind.PERSON, Kind.ADDRESS, Kind.PHONE, Kind.EMAIL}),
)


@dataclass(frozen=True)
class ChatResult:
    intent: Intent
    reply: str
    event_ids: list[str]
    need_wider: bool = False  # 목록이 부족하다고 모델이 표시함 — 아래 세 값으로 서버가 다시 거른다
    period_start: str = ""
    period_end: str = ""
    keyword: str = ""
    register: dict = field(default_factory=dict)  # intent 가 register 일 때 모델이 읽은 값(검증 끝)
    target_id: str = ""  # intent 가 edit·delete 일 때 모델이 고른 일정 id(보여 준 목록에 있는 것만)
    all_targets: bool = False  # delete 일 때 여러 건을 한꺼번에 지우라는 말(대상은 event_ids)
    also_delete_title: str = (
        ""  # 주된 요청 말고 같은 문장에서 지우라고 한 일정의 제목(삭제는 확인 카드)
    )
    target_unnamed: bool = False  # 일정을 이름·날짜 없이 가리킨 문장(대상을 되묻는다)
    changes: dict = field(default_factory=dict)  # intent 가 edit 일 때 모델이 읽은 바뀔 값(검증 끝)
    check_action: str = ""  # intent 가 check 일 때 mark / unmark / list (아니면 빈 문자열)
    request: dict = field(default_factory=dict)  # intent 가 request 일 때 모델이 읽은 값(검증 끝)
    habit: dict = field(default_factory=dict)  # intent 가 habit 일 때 모델이 읽은 값(검증 끝)


def clean_result(
    data: dict,
    allowed_ids: set[str],
    member_ids: set[str] | None = None,
    request_ids: set[str] | None = None,
    habit_ids: set[str] | None = None,
) -> dict:
    """LLM 출력을 믿지 않고 검증한다: 보기 밖 종류는 일정 요청이 아닌 것으로, 목록에 없는 id 는 버린다."""
    if not isinstance(data, dict):
        data = {}
    intent = data.get("intent")
    intent = intent if intent in INTENTS else "not_schedule"
    reply = data.get("reply")
    reply = reply.strip()[:MAX_REPLY_CHARS] if isinstance(reply, str) else ""
    ids = data.get("event_ids")
    ids = ids if isinstance(ids, list) else []
    target = data.get("target_id")
    also = data.get("also_delete_title")
    action = data.get("check_action")
    seen: list[str] = []
    for value in ids:
        if isinstance(value, str) and value in allowed_ids and value not in seen:
            seen.append(value)
    return {
        "intent": intent,
        "reply": reply,
        "event_ids": seen[:MAX_EVENT_IDS],
        "all_targets": data.get("all_targets") is True,
        "also_delete_title": _short(also, 40),
        "target_unnamed": data.get("target_unnamed") is True,
        "need_wider": data.get("need_wider") is True,
        "period_start": _short(data.get("period_start"), 10),
        "period_end": _short(data.get("period_end"), 10),
        "keyword": _short(data.get("keyword"), MAX_KEYWORD_CHARS),
        "register": register.clean_fields(data.get("register"), member_ids or set()),
        "target_id": target if isinstance(target, str) and target in allowed_ids else "",
        "changes": modify.clean_changes(data.get("changes"), member_ids or set()),
        "check_action": action if action in ("mark", "unmark", "list") else "",
        "request": request_flow.clean_fields(
            data.get("request"), member_ids or set(), request_ids or set()
        ),
        "habit": habits.clean_fields(data.get("habit"), habit_ids or set()),
    }


def _short(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def event_line(
    event_id: str,
    when: datetime,
    title: str,
    time_text: str | None = None,
    shared: bool = False,
    share_ids: list[str] | None = None,
) -> str:
    """LLM 에 보내는 한 줄: id · 날짜 시간 · 제목만(메모 등은 보내지 않아 양과 노출을 줄인다).
    time_text 는 시간 표기(예: 14:00~15:00, 시간 미정). 없으면 시작 시각만 쓴다. 공동 일정은 끝에 '| 공동'을 붙인다.
    share_ids 는 내가 공유한 원본 일정의 공유 대상(구성원 id)이다 — 공유받은 사람과 가족 채팅에는 넘기지 않는다(누구에게 공유됐는지 숨긴다)."""
    clock = time_text if time_text is not None else f"{when:%H:%M}"
    line = f"{event_id} | {prompts.format_day(when)} {clock} | {mask_text(title)}"
    line = f"{line} | 공동" if shared else line
    return f"{line} | 공유:{','.join(share_ids)}" if share_ids else line


SHARED_MARK = "(공)"  # 공동(가족과 공유된) 일정
TOGETHER_MARK = "(함)"  # 함께하기(부탁)


def mark_titles(text: str, tagged) -> str:
    """질의 답에 나온 일정·부탁 제목 뒤에 표시를 붙인다. tagged 는 (제목, 표시) 쌍이고 표시가 빈 글자면 붙이지 않는다.
    공동 여부는 AI 가 아니라 DB 값(shared)으로 정해진 표시를 코드가 직접 붙인다. 이미 표시가 붙은 곳은 그대로 두고,
    같은 제목이 서로 다른 표시(없음 포함)로 섞여 있으면 어느 쪽 말인지 알 수 없어 붙이지 않는다."""
    marks: dict[str, set[str]] = {}
    for title, mark in tagged:
        for t in {title, mask_text(title)}:
            if t:
                marks.setdefault(t, set()).add(mark)
    if not marks:
        return text
    # 모든 제목을 한 번에, 긴 제목부터 찾는다: 짧은 제목이 긴 제목(표시가 있든 없든) 안에 들어 있어도 잘못 붙지 않는다
    pattern = re.compile("|".join(re.escape(t) for t in sorted(marks, key=len, reverse=True)))

    def repl(m: re.Match) -> str:
        found = marks[m.group(0)]
        mark = next(iter(found)) if len(found) == 1 else ""
        done = mark and text[m.end() : m.end() + len(mark)] == mark
        return m.group(0) + ("" if done else mark)

    return pattern.sub(repl, text)


def mark_shared(text: str, events) -> str:
    """일정 목록용: 공동(shared) 일정 제목 뒤에 (공)을 붙인다."""
    return mark_titles(
        text, [(e.title, SHARED_MARK if getattr(e, "shared", False) else "") for e in events]
    )


def _draft_block(draft: Draft | None, title: str, place: str, memo: str) -> str:
    if draft is None:
        return ""
    return (
        f"종류: {'부탁' if draft.mode == 'request' else '일정'}\n"
        f"제목: {title}\n날짜: {draft.date}\n시작: {draft.start_time}\n끝: {draft.end_time}\n"
        f"형태: {draft.kind}\n장소: {place}\n메모: {memo}\n"
        f"공유: {', '.join(draft.share_ids)}"
    )


def _observe(result: dict) -> None:
    """평가 전용 관찰 훅: 구조화 출력을 `schedule.<intent>` 호출로 담는다(꺼져 있으면 아무 일도 안 한다).
    일정 요청이 아닌 말(not_schedule)은 도구를 부르지 않은 것이다. 쓰기 결과(되묻기·대체)는 이 뒤 코드가 정하므로
    호출한 쪽이 `eval_hook.mark_last` 로 표시한다."""
    intent = result["intent"]
    if eval_hook.current() is None or intent == "not_schedule":
        return
    if intent in ("query", "recommend"):
        args = {k: result[k] for k in ("period_start", "period_end", "keyword")}
    elif intent == "register":
        args = result["register"]
    elif intent == "edit":
        args = {"target_id": result["target_id"], **result["changes"]}
    elif intent == "delete":
        args = {"target_id": result["target_id"]}
    elif intent == "check":
        args = {"check_action": result["check_action"], "event_ids": result["event_ids"]}
    elif intent == "request":
        args = result["request"]
    elif intent == "habit":
        args = result["habit"]
    else:
        args = {}
    # 목록이 부족하다고 표시해 같은 질문을 한 번 더 분류하면(handler 의 need_wider) 앞선 결과는 대체된 것이다
    for earlier in eval_hook.current().calls:
        if earlier["stage"] == "schedule" and earlier["name"].startswith("schedule."):
            earlier["superseded"] = True
    eval_hook.observe_call("schedule", f"schedule.{intent}", args)


def converse(
    db: Session,
    user_id: str,
    group_id: str,
    text: str,
    now: datetime,
    event_lines: list[str],
    omitted: int,
    scope: str | None,
    allowed_ids: set[str],
    final: bool = False,
    members: list[Member] | None = None,
    draft: Draft | None = None,
    guarded: bool = True,
    request_lines: list[str] | None = None,
    request_ids: set[str] | None = None,
    notice: str = "",
    habit_lines: list[str] | None = None,
    habit_ids: set[str] | None = None,
) -> ChatResult:
    members = members or []
    member_ids = {m.id for m in members}
    # 가명화할 줄: 1 사용자 문장, 2~4 초안의 제목·장소·메모, 100~ 구성원
    rows = [Row(1, "", text)]
    if draft is not None:
        rows += [Row(2, "", draft.title), Row(3, "", draft.place), Row(4, "", draft.memo)]
    rows += [Row(100 + i, "", line(m)) for i, m in enumerate(members)]
    with prepare_transcript(rows, names(members), POLICY, speaker_tokens=False) as prep:
        if prep.blocked_ids:
            # 주민번호·카드·계좌 같은 것은 외부 모델로 보내지 않는다(AI 를 부르지 않고 한도도 쓰지 않는다)
            raise bad_request(
                "sensitive_content", "주민번호·카드·계좌 같은 민감정보가 있어 처리하지 않았어요"
            )
        sent = {ln.id: ln.text for ln in prep.lines}
        prompt = prompts.chat_prompt(
            sent[1],
            now,
            event_lines,
            omitted,
            scope,
            final,
            member_lines=[sent[100 + i] for i in range(len(members))],
            draft_block=_draft_block(draft, sent.get(2, ""), sent.get(3, ""), sent.get(4, "")),
            request_lines=request_lines,
            notice=notice,
            habit_lines=habit_lines,
        )

        def call():
            response = llm.complete_json(
                prompt,
                prompts.CHAT_SCHEMA,
                system=prompts.CHAT_SYSTEM,
                max_tokens=1600,
                model=prompts.CHAT_MODEL,
            )
            return clean_result(
                response.data, allowed_ids, member_ids, request_ids, habit_ids
            ), response

        # 같은 가족이 같은 날 같은 일정 목록에서 같은 말을 하면 캐시를 쓴다(목록이 바뀌면 키가 달라진다).
        # 캐시에는 가명화된(토큰 상태의) 결과가 들어가고, 돌려줄 때 이 요청의 대응표로 복원한다.
        key = hashlib.sha256(prompt.encode()).hexdigest()
        if guarded:
            outcome = ai_guard.run(
                db, user_id=user_id, group_id=group_id, feature=FEATURE, cache_key=key, call=call
            )
            result_data = outcome.result
        else:
            # 메인 채팅이 이미 동의·쿨다운·한도를 확인했다. 여기서 또 지나지 않고 호출 수만 메인 질문에 더한다
            try:
                result_data, response = call()
            except (llm.LLMUnavailable, ValueError) as exc:
                ai_guard.count_nested(None, getattr(exc, "calls", 1))
                raise ApiError(
                    503, "llm_failed", "AI 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요"
                ) from None
            ai_guard.count_nested(response)
        cleaned = clean_result(result_data, allowed_ids, member_ids, request_ids, habit_ids)
        restored = restore_json(
            prep,
            {
                "reply": cleaned["reply"],
                "register": cleaned["register"],
                "changes": cleaned["changes"],
                "request": cleaned["request"],
            },
            generalize_unknown=True,
            scrub=True,
        ).value
    cleaned["reply"] = restored["reply"]
    cleaned["register"] = register.clean_fields(restored["register"], member_ids)
    cleaned["changes"] = modify.clean_changes(restored["changes"], member_ids)
    cleaned["request"] = request_flow.clean_fields(
        restored["request"], member_ids, request_ids or set()
    )
    _observe(cleaned)
    return ChatResult(**cleaned)
