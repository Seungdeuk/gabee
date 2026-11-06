"""통합관리자 챗봇. 질문을 Claude API 로 바로 보낸다(임베딩·검색 없음).

Claude 는 가비의 규칙을 모르므로 answer_format.md(답 형식)와 faq.md(규칙)를 지시로 함께 준다. 일상 질문 거절도 Claude 가 한다.
팀 문서를 넣는 곳은 faq.md 하나이고, 가족 데이터는 다루지 않는다."""

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.features.ai_assistant.ingest.masking import mask_text
from app.shared.errors import ApiError
from app.shared.llm import client as llm

from .live import live_summary
from .schemas import AdminAskOut

log = logging.getLogger(__name__)
ASK_MAX_TOKENS = 2000
ASK_DAILY_LIMIT = 100  # 관리자 한 명의 하루 질문 수(서버 메모리, 비용 보호)
FOLDER = Path(__file__).parent
FAQ = (FOLDER / "faq.md").read_text(encoding="utf-8")
# 말투와 답 모양은 answer_format.md, 가비 규칙은 faq.md 에서 고친다. 서버가 켜질 때 읽는다
ASK_SYSTEM = (FOLDER / "answer_format.md").read_text(encoding="utf-8") + f"\n자료:\n{FAQ}"
_ask_counts: dict[tuple[str, str], int] = {}


def _within_limit(user_id: str, now: datetime) -> bool:
    key = (user_id, now.date().isoformat())
    if _ask_counts.get(key, 0) >= ASK_DAILY_LIMIT:
        return False
    _ask_counts[key] = _ask_counts.get(key, 0) + 1
    return True


def ask(db: Session, user_id: str, question: str, now: datetime | None = None) -> AdminAskOut:
    """키가 없으면 503 ai_key_missing, 하루 한도를 넘으면 429 ai_daily_limit, 호출이 실패하면 503 llm_failed."""
    if not llm.available():
        raise ApiError(503, "ai_key_missing", "AI 키가 아직 설정되지 않았어요")
    if not _within_limit(user_id, now or datetime.now(UTC)):
        raise ApiError(429, "ai_daily_limit", "오늘 질문 횟수를 다 썼어요. 내일 다시 해 주세요")
    try:
        prompt = f"현재 숫자:\n{live_summary(db)}\n\n관리자 질문: {mask_text(question)}"
        answer = llm.complete(prompt, system=ASK_SYSTEM, max_tokens=ASK_MAX_TOKENS)
    except llm.LLMUnavailable as e:
        log.warning("관리자 챗봇 호출 실패: %s", e)  # 오류 종류만 있고 질문·키는 없다
        raise ApiError(
            503, "llm_failed", "AI 가 지금 답하지 못했어요. 잠시 뒤 다시 해 주세요"
        ) from None
    return AdminAskOut(answer=answer.strip())
