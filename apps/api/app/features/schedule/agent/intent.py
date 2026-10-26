"""사용자 문장이 어떤 일정 요청인지 가른다. LLM 호출은 공통 관문 `ai_guard.run` 을 거친다."""

import hashlib

from sqlalchemy.orm import Session

from app.shared import ai_guard
from app.shared.llm import client as llm

from . import prompts
from .schemas import INTENTS, Intent


def clean_intent(data: dict) -> Intent:
    """LLM 이 보기 밖의 값을 주면 일정 요청이 아닌 것으로 본다(일정을 잘못 건드리지 않는 쪽)."""
    value = data.get("intent") if isinstance(data, dict) else None
    return value if value in INTENTS else "not_schedule"  # type: ignore[return-value]


def classify(db: Session, user_id: str, group_id: str, text: str) -> Intent:
    def call():
        response = llm.complete_json(
            prompts.intent_prompt(text),
            prompts.INTENT_SCHEMA,
            system=prompts.INTENT_SYSTEM,
            max_tokens=50,
            model=prompts.INTENT_MODEL,
        )
        return {"intent": clean_intent(response.data)}, response

    outcome = ai_guard.run(
        db,
        user_id=user_id,
        group_id=group_id,
        feature="schedule_intent",
        cache_key=hashlib.sha256(text.encode()).hexdigest(),
        call=call,
    )
    return clean_intent(outcome.result)
