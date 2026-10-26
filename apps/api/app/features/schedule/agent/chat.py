"""사용자 문장을 한 번의 LLM 호출로 분류하고 답까지 받는다(질문 1회 = 호출 1회). 호출은 공통 관문 `ai_guard.run` 을 거친다.

분류만 따로 하지 않는다: 코드는 돌려받은 intent 로 종류별 처리(확인 카드·권한 검사 등)를 정하고, 모델 출력은 그대로 믿지 않고 검증한다.
외부로 나가기 전에 개인정보를 가린다.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

# ai_assistant 기능 폴더의 app/features/ai_assistant/ingest/masking.py 에서 mask_text 함수 하나를 가져다 쓴다.
# 외부 모델로 보내는 글(일정 제목·사용자 문장)에서 주민번호·전화·카드·이메일·계좌·라벨 있는 이름·주소를 가린다.
# 이 함수의 위치나 이름을 바꾸면 여기도 고쳐야 한다.
from app.features.ai_assistant.ingest.masking import mask_text
from app.shared import ai_guard
from app.shared.llm import client as llm

from . import limits, prompts  # noqa: F401  (limits: 일정 호출 한도를 따로 세도록 등록)
from .schemas import INTENTS, Intent

FEATURE = "schedule_chat"
MAX_REPLY_CHARS = 600
MAX_EVENT_IDS = 20
MAX_KEYWORD_CHARS = 30


@dataclass(frozen=True)
class ChatResult:
    intent: Intent
    reply: str
    event_ids: list[str]
    need_wider: bool = False  # 목록이 부족하다고 모델이 표시함 — 아래 세 값으로 서버가 다시 거른다
    period_start: str = ""
    period_end: str = ""
    keyword: str = ""


def clean_result(data: dict, allowed_ids: set[str]) -> dict:
    """LLM 출력을 믿지 않고 검증한다: 보기 밖 종류는 일정 요청이 아닌 것으로, 목록에 없는 id 는 버린다."""
    if not isinstance(data, dict):
        data = {}
    intent = data.get("intent")
    intent = intent if intent in INTENTS else "not_schedule"
    reply = data.get("reply")
    reply = reply.strip()[:MAX_REPLY_CHARS] if isinstance(reply, str) else ""
    ids = data.get("event_ids")
    ids = ids if isinstance(ids, list) else []
    seen: list[str] = []
    for value in ids:
        if isinstance(value, str) and value in allowed_ids and value not in seen:
            seen.append(value)
    return {
        "intent": intent,
        "reply": reply,
        "event_ids": seen[:MAX_EVENT_IDS],
        "need_wider": data.get("need_wider") is True,
        "period_start": _short(data.get("period_start"), 10),
        "period_end": _short(data.get("period_end"), 10),
        "keyword": _short(data.get("keyword"), MAX_KEYWORD_CHARS),
    }


def _short(value, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def event_line(event_id: str, when: datetime, title: str) -> str:
    """LLM 에 보내는 한 줄: id · 날짜 시간 · 제목만(메모 등은 보내지 않아 양과 노출을 줄인다)."""
    return f"{event_id} | {prompts.format_when(when)} | {mask_text(title)}"


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
) -> ChatResult:
    prompt = prompts.chat_prompt(mask_text(text), now, event_lines, omitted, scope, final)

    def call():
        response = llm.complete_json(
            prompt,
            prompts.CHAT_SCHEMA,
            system=prompts.CHAT_SYSTEM,
            max_tokens=700,
            model=prompts.CHAT_MODEL,
        )
        return clean_result(response.data, allowed_ids), response

    # 같은 가족이 같은 날 같은 일정 목록에서 같은 말을 하면 캐시를 쓴다(목록이 바뀌면 키가 달라진다)
    key = hashlib.sha256(prompt.encode()).hexdigest()
    outcome = ai_guard.run(
        db, user_id=user_id, group_id=group_id, feature=FEATURE, cache_key=key, call=call
    )
    cleaned = clean_result(outcome.result, allowed_ids)
    return ChatResult(**cleaned)
